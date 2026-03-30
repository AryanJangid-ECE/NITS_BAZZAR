import os
import time
import json
import threading
import google.generativeai as genai

from flask import Flask, request, jsonify
from flask_cors import CORS

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from webdriver_manager.chrome import ChromeDriverManager
from webdriver_manager.core.os_manager import ChromeType
from selenium.webdriver.common.action_chains import ActionChains 
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==========================================
# 🌐 FLASK BACKEND SETUP (Database ke sath)
# ==========================================
# 'static' folder ko allow kar rahe hain taaki images website par dikh sakein
app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app) 

DB_FILE = 'products.json' # Ye humara chota sa permanent database hai

# Database se products padhne ka function
def load_products():
    if not os.path.exists(DB_FILE):
        return []
    with open(DB_FILE, 'r') as f:
        return json.load(f)

# ==========================================
# 🔥 ANTI-DUPLICATE SHIELD (Fix)
# ==========================================
def save_product(product_data):
    products = load_products()
    
    # Check karo ki kya ye same product pehle se majood hai?
    for existing_product in products:
        # Agar Product ka Naam aur Seller ka Contact match ho jaye
        if existing_product.get('product_name') == product_data.get('product_name') and existing_product.get('contact') == product_data.get('contact'):
            print(f"⚠️ [ANTI-DUPLICATE] '{product_data.get('product_name')}' pehle se website par hai. Skipping...")
            return # Yahan se function wapas laut jayega, aage nahi badhega
            
    # Agar match nahi hua, tabhi naya product add karo
    products.append(product_data)
    with open(DB_FILE, 'w') as f:
        json.dump(products, f, indent=4)
    print(f"✅ [SAVED] '{product_data.get('product_name')}' successfully added to Database!")

# 1. Naya product receive aur SAVE karne ka route
@app.route('/api/add-product', methods=['POST'])
def receive_product():
    try:
        data = request.json
        print("\n🌐 [DATABASE] Saving New Product...")
        save_product(data) # 🔥 PRODUCT HAMESHA KE LIYE SAVE HO GAYA
        return jsonify({"status": "success", "message": "Product saved permanently!"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# 2. Saare saved products ko Website par bhejne ka route (NEW)
@app.route('/api/products', methods=['GET'])
def send_all_products():
    try:
        products = load_products()
        # Naye products sabse upar dikhane ke liye reverse kar rahe hain
        return jsonify(products[::-1]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ... Baaki tumhara Gemini aur WhatsApp wala code same rahega ...


# ==========================================
# 🔥 2. GEMINI DATA EXTRACTOR FUNCTION
# ==========================================
def extract_product_details(model, message_text):
    # 🛑 SMART FILTER: Agar message bohot chota hai, toh AI ko mat bhejo
    if len(message_text.strip()) < 10 or len(message_text.split()) < 3:
        print("⏭️ [SKIP] Message bohot chota hai, ignore kiya.")
        return {
            "product_name": "Not a product message",
            "price": "N/A",
            "reason_for_selling": "N/A",
            "pic_url": "N/A"
        }

    prompt = f"""
    Extract the product details from the following WhatsApp message.
    Message: "{message_text}"
    
    Return ONLY a raw JSON object. Do NOT add Markdown, do NOT add ```json. Just the raw dictionary with these exact keys:
    {{
        "product_name": "...",
        "price": "...",
        "reason_for_selling": "...",
        "pic_url": "..."
    }}
    """
    try:
        # ⏱️ Timeout lagaya hai taaki script hang na ho
        response = model.generate_content(prompt, request_options={"timeout": 15})
        
        # Output ko saaf karke JSON banayenge
        clean_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(clean_text) 
        
    except Exception as e:
        print(f"\n❌ [ERROR] AI API Failed or Timeout: {e}")
        return {
            "product_name": "Error extracting",
            "price": "Error",
            "reason_for_selling": "Error",
            "pic_url": "Error"
        }
    
# ==========================================
# 📱 3. WHATSAPP LIVE SEARCH & MONITOR
# ==========================================
def monitor_dynamic_contact(model, contact_name):
    print("\n📱 [WHATSAPP] Initializing WhatsApp Web on Chromium...")
    options = webdriver.ChromeOptions()
    options.binary_location = "/usr/bin/chromium" 
    
    # Ye profile save rakhega taaki baar baar QR scan na karna pade
    linux_profile = os.path.join(os.path.expanduser('~'), ".config", "JarvisChromiumProfile")
    options.add_argument(f"user-data-dir={linux_profile}") 
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager(chrome_type=ChromeType.CHROMIUM).install()), options=options)
    driver.set_script_timeout(15)
    driver.get("https://web.whatsapp.com/")
    
    print("📱 [WHATSAPP] Waiting 30 seconds for WhatsApp to load. Scan QR if asked...")
    time.sleep(30) 
    
    actions = ActionChains(driver)
    
    print(f"\n📱 [WHATSAPP] Searching for target: '{contact_name}'")
    actions.key_down(Keys.CONTROL).key_down(Keys.ALT).send_keys('/').key_up(Keys.ALT).key_up(Keys.CONTROL).perform()
    time.sleep(1.5)
    
    actions.key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).send_keys(Keys.BACKSPACE).perform()
    time.sleep(0.5)
    actions.send_keys(contact_name).perform()
    time.sleep(3) 
    
    actions.send_keys(Keys.DOWN).perform() 
    time.sleep(0.5)
    actions.send_keys(Keys.ENTER).perform()
    time.sleep(3) 

    last_memory_signature = "" 
    print(f"✅ [SUCCESS] Chat opened for '{contact_name}'. Monitoring text...\n")

    while True:
        try:
            # Sirf aane wale (message-in) bubbles read karega
            all_chat_bubbles = driver.find_elements(By.CSS_SELECTOR, "div.message-in")
            if len(all_chat_bubbles) > 0:
                last_bubble = all_chat_bubbles[-1]
                raw_text = last_bubble.text.strip()
                
                # Agar naya message aaya hai tabhi process karo
                if raw_text != "" and raw_text != last_memory_signature:
                    last_memory_signature = raw_text
                    
                    clean_msg = raw_text.replace('\n', ' | ')
                    print(f"\n🚨 [WHATSAPP] New Message Detected: {clean_msg}")
                    
                    # 🛑 SMART FILTER Check
                    if len(clean_msg) > 15:
                        print("🤖 [AI] Processing text with Gemini...")
                        whatsapp_data = extract_product_details(model, clean_msg)
                        
                        # Target this section in your app.py, inside the 'if len(all_chat_bubbles) > 0:' block

                        # ... (Gemini text processing works fine) ...

                        # ==========================================
                        # 📸 MAGICAL IMAGE CAPTURE SCRIPT (Fixed & Resilient)
                        # ==========================================
                        pic_base64 = "null" # Default fallback
                        try:
                            # We need these additional imports at the top of app.py:
                            # from selenium.webdriver.support.ui import WebDriverWait
                            # from selenium.webdriver.support import expected_conditions as EC
                            
                            # Wait up to 5 seconds for an image to actually render inside that specific message bubble
                            print("⏳ [IMAGE] Waiting for image to load in Selenium...")
                            # WA Web dynamic image CSS selector can be div._amk4 img[src^='blob:']
                            # If WA Web updates, you might need to inspect the element and update this selector
                            img_element = WebDriverWait(last_bubble, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, "img[src^='blob:']"))
                            )

                            # If found, proceed to download and convert to Base64
                            print("⏳ [IMAGE] Downloading photo from WhatsApp...")
                            blob_url = img_element.get_attribute("src")
                            
                            # JS injection logic (assuming this was working before, but now triggers reliably)
                            pic_base64 = driver.execute_async_script("""
                                var uri = arguments[0];
                                var callback = arguments[1];
                                var xhr = new XMLHttpRequest();
                                xhr.open('GET', uri);
                                xhr.responseType = 'blob';
                                xhr.onload = function() {
                                    var reader = new FileReader();
                                    reader.onloadend = function() {
                                        callback(reader.result);
                                    };
                                    reader.readAsDataURL(xhr.response);
                                };
                                xhr.send();
                            """, blob_url)

                            print("✅ [IMAGE] Photo successfully captured!")

                        except Exception as e:
                            # If 5 seconds pass and no image is found, it falls here (covers text-only messages too)
                            if "TimeoutException" in str(type(e)):
                                print("⏭️ [IMAGE] No photo found in this message bubble (text-only or slow network).")
                            else:
                                print(f"❌ [IMAGE] Image extraction failed: {e}")
                            # pic_base64 remains "null"
                        # ==========================================

                        # ... (rest of the code to update products_database and return response) ...
                        print("\n📱 [WHATSAPP] --- NAYA PRODUCT AAYA HAI ---")
                        print(f"Name: {whatsapp_data.get('product_name')}")
                        print(f"Price: {whatsapp_data.get('price')}")
                        print("------------------------------------------\n")
                        
                        # Image priority set karo (WhatsApp image pehle, fir AI text link)
                        final_pic_url = pic_base64 if pic_base64 != "null" else whatsapp_data.get('pic_url', 'null')
                        
                        # Website DB me add karo
                        # ====== YAHAN FIX KIYA HAI ======
                        final_pic_url = pic_base64 if pic_base64 != "null" else whatsapp_data.get('pic_url', 'null')
                        
                        import re
                        # 1. Pehle AI ka nikala hua number check karo
                        raw_number = whatsapp_data.get('seller_number', '')
                        clean_number = re.sub(r'[^0-9]', '', str(raw_number))
                        
                        # 2. 🔥 BULLETPROOF BACKUP: Agar AI ne number miss kar diya, toh Python khud dhoondhega!
                        if len(clean_number) < 10:
                            # Message text mein koi bhi 10 digit ka number dhoondho
                            fallback_numbers = re.findall(r'\b\d{10}\b', clean_msg)
                            if fallback_numbers:
                                clean_number = fallback_numbers[-1] # Jo number mile usko utha lo
                        
                        # 3. Final Contact set karo
                        final_contact = clean_number if len(clean_number) >= 10 else f"WhatsApp: {contact_name}"

                        # Database ke liye ready
                        new_whatsapp_product = {
                            "product_name": whatsapp_data.get('product_name', 'N/A'),
                            "price": whatsapp_data.get('price', 'N/A'),
                            "category": "WhatsApp Item",
                            "pic_url": final_pic_url,
                            "reason_for_selling": whatsapp_data.get('reason_for_selling', 'N/A'),
                            "contact": final_contact # Ab yahan hamesha 6000305604 jayega!
                        }
                        
                        save_product(new_whatsapp_product)
                        # ================================
                        
                        print("🌐 [SUCCESS] Product permanently saved to Database & ready for Website!\n")
                        # ================================
                        print("🌐 [SUCCESS] Product & Photo sent to Website!\n")
                    else:
                        print("⏭️ [SKIP] Message bohot chota hai, ignore kiya.")
                    
        except Exception as e:
            pass # Chhoti moti DOM errors ko ignore karo
            
        time.sleep(3)

# ==========================================
# 🚀 4. MAIN SCRIPT RUNNER
# ==========================================
if __name__ == "__main__":
    print("\n=============================================")
    print("   🤖 NITS BAZAR + WHATSAPP AI BOOTING...  ")
    print("=============================================\n")
    
    # User Input
    LIVE_API_KEY = input("🔑 Enter your Gemini API Key: ").strip()
    if not LIVE_API_KEY:
        print("❌ Error: API Key is required. Exiting...")
        exit()

    TARGET_CONTACT = input("👤 Enter the exact WhatsApp Contact Name to search: ").strip()
    if not TARGET_CONTACT:
        print("❌ Error: Contact name cannot be empty. Exiting...")
        exit()

    # Configure API Key
    genai.configure(api_key=LIVE_API_KEY)

    # 🧠 SMART AUTO-SELECTOR: Google se khud pucho valid model ka naam
    print("\n🔍 Scanning your API Key for available models...")
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        
        if not available_models:
            print("❌ [CRITICAL ERROR] Tumhari API key par koi AI model active nahi hai. Nayi API key bana lo Google AI Studio se!")
            exit()
            
        # 'flash' model dhoondho (kyunki wo sabse fast hota hai), warna jo mile wo utha lo
        chosen_model = next((m for m in available_models if 'flash' in m.lower()), available_models[0])
        print(f"✅ AI Model successfully locked: {chosen_model}")
        
    except Exception as e:
        print(f"❌ API Key me problem hai: {e}")
        exit()

    # Us auto-selected model ko initialize karo
    gemini_model = genai.GenerativeModel(chosen_model)

    # Start WhatsApp Bot in Background
    whatsapp_thread = threading.Thread(target=monitor_dynamic_contact, args=(gemini_model, TARGET_CONTACT))
    whatsapp_thread.daemon = True 
    whatsapp_thread.start()

    # Start Web Server
    print("\n🚀 Starting Web Server for NITS Bazar Frontend...")
    app.run(debug=True, port=5000, use_reloader=False)
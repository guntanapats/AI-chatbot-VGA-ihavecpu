from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, QuickReply, QuickReplyButton, MessageAction
)
from sentence_transformers import SentenceTransformer, util
from neo4j import GraphDatabase
from linebot.models import FlexSendMessage
import json
import random
import re
import requests

# Access Token and Secret for LINE API
access_token = 'ACCESS_TOKEN'
secret = 'secret'
line_bot_api = LineBotApi(access_token)
handler = WebhookHandler(secret)

# Flask app
app = Flask(__name__)

# Dictionary to store user states
user_data = {}

# Load the sentence-transformers model
model = SentenceTransformer('sentence-transformers/distiluse-base-multilingual-cased-v2')

# Neo4j connection details
URI = "neo4j://localhost"
AUTH = ("neo4j", "PASSWORD")

# Function to run a query in Neo4j
def run_query(query, parameters=None):
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            session.run(query, parameters)

# Function to fetch all products from Neo4j
def get_all_products_from_neo4j():
    query = '''
    MATCH (p:Product)
    RETURN p.name AS name, p.price AS price, p.additional_data AS additional_data, p.img AS image, p.url AS url
    '''
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            results = session.run(query)
            return [{'name': record['name'],
                     'price': record['price'],
                     'additional_data': record['additional_data'],
                     'image': record['image'],  # Fetching the image URL
                     'url': record['url']} for record in results]

# Function to save chat history to Neo4j
def save_chat_history(user_id, user_message, bot_response):
    query = '''
    MERGE (u:User {id: $user_id})
    CREATE (q:Question {message: $user_message, timestamp: timestamp()})
    CREATE (a:Answer {response: $bot_response, timestamp: timestamp()})
    CREATE (u)-[:ASKED]->(q)
    CREATE (q)-[:HAS_ANSWER]->(a)
    '''
    parameters = {
        'user_id': user_id,
        'user_message': user_message,
        'bot_response': bot_response
    }
    run_query(query, parameters)

def ollama_response(user_message):
    ollama_api_url = "http://localhost:11434/api/generate"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "model": "supachai/llama-3-typhoon-v1.5",
        "prompt": user_message + "สรุปคำตอบโดยไม่เกิน30คำ",
        "stream": False
    }
    
    response = requests.post(ollama_api_url, headers=headers, data=json.dumps(payload))
    if response.status_code == 200:
        data = json.loads(response.text)
        return data.get("response", "") + " คำตอบจาก Ollama"
    else:
        return "ไม่สามารถตอบคำถามได้ในขณะนี้."

def is_gpu_related_question(msg):
    # Define a list of GPU-related keywords
    gpu_keywords = [
        "GPU", 
        "กราฟิกการ์ด", "วีจีเอ", "การเลือกซื้อการ์ดจอ" ,
    ]
    
    # Check if any of the GPU-related keywords are in the user's message
    for keyword in gpu_keywords:
        if keyword.lower() in msg.lower():
            return True  # Return True if the message is GPU-related
    
    return False  # Return False if the message is not related to GPU

@app.route("/", methods=['POST'])
def linebot():
    body = request.get_data(as_text=True)
    signature = request.headers.get('X-Line-Signature')

    # Verify the signature
    if not signature:
        abort(400)

    try:
        handler.handle(body, signature)  # Handle the webhook event
    except InvalidSignatureError:
        abort(400)
    except Exception as e:
        print(f"Error: {e}")  # Log any other errors

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text  # Get the user's message
    reply_token = event.reply_token  # Get the reply token

    # Check if user exists in the session
    if user_id not in user_data:
        user_data[user_id] = {}

    # Step 0: Respond with a random greeting message and initial quick replies
    if 'step' not in user_data[user_id]:
        user_data[user_id]['step'] = 0

        # Pick a random greeting from the list
        random_greeting = random.choice(['สวัสดีครับ', 'สวัสดีค่ะ'])
        welcome_message = f"{random_greeting} g Test พร้อมใช้งานครับ สามารถเลือก spec การ์ดจอได้เลยครับ"

        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="แนะนำการ์ดจอ", text="แนะนำการ์ดจอ")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ NVDIA", text="การ์ดจอ NVDIA")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ AMD", text="การ์ดจอ AMD")),
            ]
        )

        # Reply to the user
        bot_response = welcome_message
        line_bot_api.reply_message(reply_token, TextSendMessage(text=bot_response, quick_reply=quick_reply))

        # Save chat history
        save_chat_history(user_id, msg, bot_response)

        user_data[user_id]['step'] = 1
        return

    # Step 1: If user selects "แนะนำการ์ดจอ"
    if msg == "แนะนำการ์ดจอ":
        bot_response = "Here are some GPU recommendations..."
        send_gpu_recommendations(user_id)

        # Save chat history
        save_chat_history(user_id, msg, bot_response)
        return

    
    # Step 2: If user selects "การ์ดจอ NVDIA" or "การ์ดจอ AMD"
    if msg in ["การ์ดจอ NVDIA", "การ์ดจอ AMD"]:
        user_data[user_id]['gpu_type'] = msg  # Store the selected GPU type

        bot_response = "ขอทราบราคาครับ"
        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="5000 บาท", text="5000 บาท")),
                QuickReplyButton(action=MessageAction(label="10000 บาท", text="10000 บาท")),
                QuickReplyButton(action=MessageAction(label="15000 บาท", text="15000 บาท")),
                QuickReplyButton(action=MessageAction(label="25000 บาท", text="25000 บาท")),
                QuickReplyButton(action=MessageAction(label="35000 บาท", text="35000 บาท")),
                QuickReplyButton(action=MessageAction(label="50000 บาท", text="50000 บาท")),
                QuickReplyButton(action=MessageAction(label="80000 บาท", text="80000 บาท")),
                QuickReplyButton(action=MessageAction(label="100000 บาท", text="100000 บาท")),
            ]
        )
        line_bot_api.reply_message(reply_token, TextSendMessage(text=bot_response, quick_reply=quick_reply))

        # Save chat history
        save_chat_history(user_id, msg, bot_response)

        user_data[user_id]['step'] = 2
        return
    # Step 0 Continued: Handle messages outside quick replies in step 0
    if user_data[user_id]['step'] == 0:
        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="แนะนำการ์ดจอ", text="แนะนำการ์ดจอ")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ NVDIA", text="การ์ดจอ NVDIA")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ AMD", text="การ์ดจอ AMD")),
            ]
        )

        if is_gpu_related_question(msg):
            # Use Ollama to respond if the question is within the GPU scope but not in quick replies
            bot_response = ollama_response(msg)
        else:
            # If the question is outside the GPU scope, reply with the message and show quick replies again
            bot_response = "ผมไม่สามารถตอบคำถามนอกเหนือจาก GPU ได้ครับ"

        # Always display the response with quick replies in step 0
        line_bot_api.reply_message(reply_token, TextSendMessage(text=bot_response, quick_reply=quick_reply))

        # Save chat history
        save_chat_history(user_id, msg, bot_response)
        return
    # Step 3: If user selects a price
    if user_data[user_id]['step'] == 2:
        # Try to extract a numeric value from the user's input (e.g., "5000 บาท")
        if isinstance(msg, str):  # Ensure msg is a string
            price_match = re.search(r'(\d+)', msg)  # Extract numeric value from message
            
            if price_match:
                price_value = int(price_match.group(1))
                
                # Validate the price is in the correct range
                if 5000 <= price_value <= 100000:
                    user_data[user_id]['price'] = price_value  # Store the valid price
                    bot_response = "ขอทราบรายละเอียดเพิ่มเติมครับ"  # Proceed to RAM selection
                    
                    quick_reply = QuickReply(
                        items=[
                            QuickReplyButton(action=MessageAction(label="RAM 4 GB", text="RAM 4 GB")),
                            QuickReplyButton(action=MessageAction(label="RAM 6 GB", text="RAM 6 GB")),
                            QuickReplyButton(action=MessageAction(label="RAM 8 GB", text="RAM 8 GB")),
                            QuickReplyButton(action=MessageAction(label="RAM 12 GB", text="RAM 12 GB")),
                        ]
                    )
                    
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
                    user_data[user_id]['step'] = 3  # Proceed to the next step (RAM selection)
                else:
                    # Reset step if price is out of range and ask again
                    user_data[user_id]['step'] = 2  # Stay at price selection
                    bot_response = "กรุณาเลือกราคาภายในช่วง 5000-100000 บาทครับ"
                    
                    quick_reply = QuickReply(
                        items=[
                            QuickReplyButton(action=MessageAction(label="5000 บาท", text="5000 บาท")),
                            QuickReplyButton(action=MessageAction(label="10000 บาท", text="10000 บาท")),
                            QuickReplyButton(action=MessageAction(label="15000 บาท", text="15000 บาท")),
                            QuickReplyButton(action=MessageAction(label="25000 บาท", text="25000 บาท")),
                            QuickReplyButton(action=MessageAction(label="35000 บาท", text="35000 บาท")),
                            QuickReplyButton(action=MessageAction(label="50000 บาท", text="50000 บาท")),
                            QuickReplyButton(action=MessageAction(label="80000 บาท", text="80000 บาท")),
                            QuickReplyButton(action=MessageAction(label="100000 บาท", text="100000 บาท")),
                        ]
                    )
                    
                    line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
            else:
                # Handle case when no numeric value was found and ask again
                user_data[user_id]['step'] = 2  # Stay at price selection
                bot_response = "กรุณาระบุราคาเป็นตัวเลขครับ"
                
                quick_reply = QuickReply(
                    items=[
                        QuickReplyButton(action=MessageAction(label="5000 บาท", text="5000 บาท")),
                        QuickReplyButton(action=MessageAction(label="10000 บาท", text="10000 บาท")),
                        QuickReplyButton(action=MessageAction(label="15000 บาท", text="15000 บาท")),
                        QuickReplyButton(action=MessageAction(label="25000 บาท", text="25000 บาท")),
                        QuickReplyButton(action=MessageAction(label="35000 บาท", text="35000 บาท")),
                        QuickReplyButton(action=MessageAction(label="50000 บาท", text="50000 บาท")),
                        QuickReplyButton(action=MessageAction(label="80000 บาท", text="80000 บาท")),
                        QuickReplyButton(action=MessageAction(label="100000 บาท", text="100000 บาท")),
                    ]
                )
                
                line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
        else:
            # Invalid input, reset and ask for price again
            user_data[user_id]['step'] = 2
            bot_response = "ผมไม่สามารถตอบคำถามนอกเหนือจาก GPU ได้ครับ"
            quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="แนะนำการ์ดจอ", text="แนะนำการ์ดจอ")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ NVDIA", text="การ์ดจอ NVDIA")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ AMD", text="การ์ดจอ AMD")),
            ]
        )
            line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
        return

    # Step 4: If user selects RAM
    if user_data[user_id]['step'] == 3:
        valid_ram_options = ["RAM 4 GB", "RAM 6 GB", "RAM 8 GB", "RAM 12 GB"]
        
        if msg in valid_ram_options:
            user_data[user_id]['ram'] = msg  # Store the valid RAM
            bot_response = "กำลังค้นหาการ์ดจอที่ตรงกับความต้องการของคุณ..."
            line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response)))
            
            # Proceed with the GPU search
            search_and_reply_with_results(user_id)
            
            user_data[user_id]['step'] = 0  # Reset the conversation state
        else:
            # Invalid RAM input, reset and ask again
            user_data[user_id]['step'] = 3  # Stay at RAM selection
            bot_response = "กรุณาเลือกระหว่าง RAM 4 GB, 6 GB, 8 GB หรือ 12 GB ครับ"
            
            quick_reply = QuickReply(
                items=[
                    QuickReplyButton(action=MessageAction(label="RAM 4 GB", text="RAM 4 GB")),
                    QuickReplyButton(action=MessageAction(label="RAM 6 GB", text="RAM 6 GB")),
                    QuickReplyButton(action=MessageAction(label="RAM 8 GB", text="RAM 8 GB")),
                    QuickReplyButton(action=MessageAction(label="RAM 12 GB", text="RAM 12 GB")),
                ]
            )
            
            line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
        return

    # If user asks something outside of GPU-related questions
    if not is_gpu_related_question(msg):
        user_data[user_id]['step'] = 0  # Reset the conversation
        bot_response = "ผมไม่สามารถตอบคำถามนอกเหนือจาก GPU ได้ครับ"
        quick_reply = QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="แนะนำการ์ดจอ", text="แนะนำการ์ดจอ")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ NVDIA", text="การ์ดจอ NVDIA")),
                QuickReplyButton(action=MessageAction(label="การ์ดจอ AMD", text="การ์ดจอ AMD")),
            ]
        )
        line_bot_api.reply_message(reply_token, TextSendMessage(text=str(bot_response), quick_reply=quick_reply))
        return


def send_gpu_recommendations(user_id):
    # Define the price ranges
    price_ranges = [5000, 10000, 15000, 20000, 35000, 50000, 100000]
    
    # Initialize an empty list to store one product per price range
    all_recommendations = []

    for price in price_ranges:
        # Fetch the best GPU for the current price range
        product_in_range = get_one_product_for_price_range(price)
        if product_in_range:
            all_recommendations.append(product_in_range)  # Only one product per price range

    bot_response = "Here are GPU recommendations based on your request."
    
    # Send a Flex message containing the recommendations for all price ranges
    if all_recommendations:
        send_flex_message(user_id, all_recommendations)
    else:
        bot_response = "ไม่มีการ์ดจอที่แนะนำในช่วงนี้"
        line_bot_api.push_message(user_id, TextSendMessage(text=bot_response))

    # Save chat history
    save_chat_history(user_id, "แนะนำการ์ดจอ", bot_response)

def get_one_product_for_price_range(max_price):
    query = '''
    MATCH (p:Product)
    RETURN p.name AS name, p.price AS price, p.additional_data AS additional_data, p.img AS image, p.url AS url
    '''
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            results = session.run(query)
            closest_product = None
            min_price_diff = float('inf')  # To track the product closest to the max_price
            
            for record in results:
                price_value = float(re.sub(r'[^\d.]', '', record['price']))  # Clean price
                if price_value <= max_price:
                    price_diff = abs(max_price - price_value)  # Calculate price difference
                    if price_diff < min_price_diff:  # Check if it's the closest to max_price
                        closest_product = {
                            'name': record['name'],
                            'price': record['price'],
                            'image': record['image'],
                            'additional_data': record['additional_data'],
                            'url': record['url']
                        }
                        min_price_diff = price_diff  # Update the closest product

            return closest_product  # Return the closest product in the price range
    return None


def get_products_for_price_range(max_price):
    query = '''
    MATCH (p:Product)
    RETURN p.name AS name, p.price AS price, p.additional_data AS additional_data, p.img AS image, p.url AS url
    '''
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            results = session.run(query)
            products = []
            for record in results:
                price_value = float(re.sub(r'[^\d.]', '', record['price']))
                if price_value <= max_price:
                    products.append({
                        'name': record['name'],
                        'price': record['price'],
                        'image': record['image'],
                        'additional_data': record['additional_data'],
                        'url': record['url']
                    })
            return products
    return []

def search_and_reply_with_results(user_id):
    # Prepare search query based on user input
    user_price_str = str(user_data[user_id]['price'])  # Ensure it's a string
    user_ram = str(user_data[user_id]['ram'])  # Ensure RAM is a string
    gpu_type = user_data[user_id].get('gpu_type', '')  # Get the GPU type
    
    print(f"Searching for products with Price: {user_price_str}, RAM: {user_ram}, GPU Type: {gpu_type}")

    # Convert user's price to a float for comparison
    try:
        user_price = float(re.sub(r'[^\d.]', '', user_price_str))  # Remove non-numeric characters
    except ValueError:
        user_price = 0

    # Fetch all products from Neo4j to compare
    all_products = get_all_products_from_neo4j()
    if not all_products:
        print("No products found from the database.")
        return

    print(f"Total products fetched: {len(all_products)}")

    # Find the best matches based on price proximity and ensure no overpricing
    matches = []
    for product in all_products:
        # Ensure all product data is present and a string
        product_name = str(product.get('name', ''))
        product_price_str = str(product.get('price', ''))
        product_image = str(product.get('image', ''))
        product_additional_data = str(product.get('additional_data', ''))
        product_url = str(product.get('url', ''))

        # Clean the price for comparison
        try:
            product_price = float(re.sub(r'[^\d.]', '', product_price_str))  # Remove non-numeric characters
        except ValueError:
            product_price = 0
        
        # Extract RAM size from additional_data
        ram_match = re.search(r'Memory Size\s*(\d+GB)', product_additional_data, re.IGNORECASE)
        if ram_match:
            product_ram_size = ram_match.group(1)  # e.g., "8GB"
            product_ram_size_value = int(product_ram_size.replace('GB', '').strip())

            # Check if product meets the RAM, price, and GPU type criteria
            if (product_price <= user_price and  # Ensure product price is less than or equal to user price
                product_ram_size_value >= int(user_ram.split()[1]) and
                ((gpu_type == "การ์ดจอ NVDIA" and "GEFORCE" in product_name.upper()) or
                 (gpu_type == "การ์ดจอ AMD" and "RADEON" in product_name.upper()))):
                 
                print(f"Matched product: {product_name}, Price: {product_price_str}, RAM: {product_ram_size}")

                # Calculate the price difference and store the product with its price difference
                price_difference = abs(product_price - user_price)  # How close the product's price is to the user price
                matches.append({
                    'name': product_name,
                    'price': product_price_str,
                    'image': product_image,
                    'url': product_url,
                    'additional_data': product_additional_data,
                    'price_difference': price_difference  # Store the price difference for sorting
                })

    # Sort the products by how close they are to the user's selected price
    matches.sort(key=lambda x: x['price_difference'])

    # Debugging output to check matches
    print(f"Total matched products: {len(matches)}")

    # Send Flex messages for the closest GPUs (within the price range)
    if matches:
        send_flex_message(user_id, matches)
    else:
        bot_response = "ไม่พบสินค้าที่ตรงกับความต้องการของคุณ."
        line_bot_api.push_message(user_id, TextSendMessage(text=str(bot_response)))

def send_flex_message(user_id, products):
    if not products:
        text_message = TextSendMessage(
            text="ไม่พบสินค้าตามที่ค้นหา.",
            quick_reply=main_quick_reply()  # Add Quick Reply when no product is found
        )
        line_bot_api.push_message(user_id, text_message)
        return

    # Limit the number of products to 6 for the Flex Message
    limited_products = products[:6]

    # Generate Flex Message bubbles with button linking to the product URL
    bubbles = []
    for prod in limited_products:
        bubble = {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": prod['image'],  # Use the image URL fetched from Neo4j
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": prod['name'], "weight": "bold", "size": "md", "wrap": True},
                    {"type": "text", "text": f"Price: {prod['price']}", "size": "sm", "color": "#999999"}
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "button",
                        "style": "primary",
                        "height": "sm",
                        "color": "#992c34",
                        "action": {
                            "type": "uri",
                            "label": "More Details",
                            "uri": prod['url']  # Link to product page
                        }
                    }
                ],
                "flex": 0
            }
        }
        bubbles.append(bubble)

    # Create Flex Message content
    contents = {"type": "carousel", "contents": bubbles}

    flex_message = FlexSendMessage(
        alt_text="Product List",
        contents=contents
    )

    # Push the Flex Message to the user
    line_bot_api.push_message(user_id, flex_message)

    # After sending the Flex Message, push a TextSendMessage with the main quick reply
    text_message = TextSendMessage(
        text="ต้องการค้นหาการ์ดจอเพิ่มเติมหรือไม่?",  # Message prompting further interaction
        quick_reply=main_quick_reply()  # Add the main quick reply options here
    )

    # Push the main quick reply message
    line_bot_api.push_message(user_id, text_message)



def main_quick_reply():
    return QuickReply(
        items=[
            QuickReplyButton(action=MessageAction(label="แนะนำการ์ดจอ", text="แนะนำการ์ดจอ")),
            QuickReplyButton(action=MessageAction(label="การ์ดจอ NVDIA", text="การ์ดจอ NVDIA")),
            QuickReplyButton(action=MessageAction(label="การ์ดจอ AMD", text="การ์ดจอ AMD")),
        ]
    )

if __name__ == '__main__':
    app.run(port=5000)

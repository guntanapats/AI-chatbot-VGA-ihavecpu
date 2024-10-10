from selenium import webdriver
from bs4 import BeautifulSoup
import time
import re
from neo4j import GraphDatabase

# Neo4j connection
URI = "neo4j://localhost"
AUTH = ("neo4j", "PASSWORD")

# Function to run a query in Neo4j
def run_query(query, parameters=None):
    with GraphDatabase.driver(URI, auth=AUTH) as driver:
        with driver.session() as session:
            session.run(query, parameters)
    driver.close()

# Function to delete all product nodes before scraping
def delete_existing_products():
    query = '''
    MATCH (p:Product)
    DETACH DELETE p
    '''
    run_query(query)

# Function to store a product in Neo4j
def save_product_to_neo4j(product_data):
    query = '''
    MERGE (p:Product {name: $name})
    SET p.price = $price, p.img = $img, p.url = $url, p.additional_data = $additional_data
    '''
    run_query(query, product_data)

# URL of the webpage to scrape (main product listing page)
url = 'https://ihavecpu.com/category/graphic-card'

# Set up the web driver
driver = webdriver.Chrome()  # Ensure you have the correct driver installed
driver.get(url)  # Open the webpage

# Give the page some time to fully load
time.sleep(5)

all_products = []

# Function to format product data dynamically
def format_product_data_dynamically(product_text):
    # Use regex to capture patterns like "Key: Value"
    pattern = re.compile(r'([A-Za-z®™ ]+):? ([\w®™\s.,:-]+)')
    
    matches = pattern.findall(product_text)
    
    if matches:
        formatted_data = ""
        for key, value in matches:
            formatted_data += f"{key.strip()}: {value.strip()}\n"
        return formatted_data
    else:
        # If no pattern is found, return the raw text
        return product_text

# Delete existing product nodes before starting scraping
delete_existing_products()

print("Starting product scraping...")

# Loop through all pages
while True:
    # Parse the main product listing page source with BeautifulSoup
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    
    # Extract product name, price, and product link
    product_containers = soup.find_all('div', class_='sc-499601bf-0 sc-a93f122a-0 iAXtGY lksMCx')  # Corrected class
    
    # Store the data
    for container in product_containers:
        # Safely extract product name
        product_name_tag = container.find('h3', class_='sc-96a18268-0 gApukh')
        product_name = product_name_tag.get_text(strip=True) if product_name_tag else 'N/A'  # Handle missing product name
        
        # Safely extract product price
        product_price_tag = container.find('span', class_='sc-96a18268-0 cDBdbZ')
        product_price = product_price_tag.get_text(strip=True) if product_price_tag else 'N/A'  # Handle missing price

        # Safely extract product URL
        product_url_tag = container.get('href')
        product_url = "https://ihavecpu.com" + product_url_tag if product_url_tag else 'N/A'  # Handle missing URL
        
        if product_url != 'N/A':
            # Open the individual product page to scrape the image
            driver.execute_script("window.open('');")
            driver.switch_to.window(driver.window_handles[1])  # Switch to the new tab
            driver.get(product_url)  # Open product page
            time.sleep(3)  # Give some time for the product page to load
            
            # Parse the product page with BeautifulSoup
            product_soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Scrape the image URL from the product page
            image_containers = product_soup.find_all('div', class_='sc-499601bf-0 edAFiM')
            product_img = 'N/A'
            for img_container in image_containers:
                img_tag = img_container.find('img')
                product_img = img_tag['src'] if img_tag else 'N/A'  # Extract the src attribute
            
            # Scrape additional product details (if any)
            table_div = product_soup.find('div', class_='sc-86152792-0 WLBSm')
            if table_div:
                table_data = table_div.get_text(strip=True)
                # Format the data dynamically
                formatted_table_data = format_product_data_dynamically(table_data)
            else:
                formatted_table_data = "N/A"  # If the table or div is not found
            
            # Add product data
            product_data = {
                'name': product_name,
                'price': product_price,
                'img': product_img,
                'url': product_url,
                'additional_data': formatted_table_data
            }
            
            # Save product to Neo4j
            save_product_to_neo4j(product_data)
            
            # Add all data to the product list
            all_products.append(product_data)
            
            # Close the current tab and switch back to the original tab
            driver.close()
            driver.switch_to.window(driver.window_handles[0])  # Switch back to original tab
    
    # Check if the "Next" button is disabled
    next_button_disabled = soup.find('li', class_='next disabled')
    if next_button_disabled:
        break  # Stop if the next button is disabled

    # Find the "Next" button and click it if available
    try:
        next_button = driver.find_element('xpath', "//li[contains(@class, 'next')]/a")
        next_button.click()
        time.sleep(5)  # Wait for the next page to load
    except:
        break  # Exit the loop if the "Next" button is not found

# Close the web driver
driver.quit()

print("Scraping finished. All products have been saved to Neo4j.")

# Print all products
for product in all_products:
    print(f"Product Name: {product['name']}")
    print(f"Price: {product['price']}")
    print(f"Image URL: {product['img']}")
    print(f"URL: {product['url']}")
    print(f"Additional Data: {product['additional_data']}")
    print("\n")

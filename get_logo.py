import urllib.request
import re

try:
    req = urllib.request.Request('https://cust.edu.pk/', headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    urls = re.findall(r'src=["\'](https://cust\.edu\.pk/[^"\']+logo[^"\']*\.png)["\']', html, re.IGNORECASE)
    print("Found URLs:", urls)
    if urls:
        img_req = urllib.request.Request(urls[0], headers={'User-Agent': 'Mozilla/5.0'})
        img_data = urllib.request.urlopen(img_req).read()
        with open('c:\\Users\\HaMad\\Desktop\\AntiGravity\\static\\cust_logo.png', 'wb') as f:
            f.write(img_data)
        print("Successfully downloaded to static/cust_logo.png")
except Exception as e:
    print("Error:", e)

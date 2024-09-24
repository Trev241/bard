from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from dotenv import load_dotenv

import os
import time
import chromedriver_autoinstaller

load_dotenv()

SCREENSHOT_PATH = "../launcher/public/images"


def signin():
    chromedriver_autoinstaller.install()

    email = os.getenv("YT_EMAIL")
    passw = os.getenv("YT_PASSW")
    screenshot_idx = 0

    # Set up Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    # Set up the WebDriver
    driver = webdriver.Chrome(options=chrome_options)

    try:
        # Open YouTube
        driver.get("https://www.youtube.com")
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1

        login_button = driver.find_element(By.LINK_TEXT, "Sign in")
        login_button.click()

        time.sleep(3)

        # Enter email
        email_input = driver.find_element(By.XPATH, '//*[@type="email"]')
        email_input.send_keys(email)
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1
        driver.find_element(By.XPATH, '//*[@id="identifierNext"]').click()

        # Wait for password page to load
        time.sleep(3)

        # Enter password
        password_input = driver.find_element(By.XPATH, '//*[@type="password"]')
        password_input.send_keys(passw)
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1
        driver.find_element(By.XPATH, '//*[@id="passwordNext"]').click()

        # Wait for the main page to load
        time.sleep(5)

        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1

        # Extract cookies
        cookies = driver.get_cookies()

        # Convert cookies to Netscape string
        result = []
        for cookie in cookies:
            domain = cookie.get("domain", "")
            expiration_date = cookie.get("expiry", None)
            path = cookie.get("path", "")
            secure = cookie.get("secure", False)
            name = cookie.get("name", "")
            value = cookie.get("value", "")

            include_sub_domain = domain.startswith(".") if domain else False
            expiry = str(int(expiration_date)) if expiration_date else "0"

            result.append(
                [
                    domain,
                    str(include_sub_domain).upper(),
                    path,
                    str(secure).upper(),
                    expiry,
                    name,
                    value,
                ]
            )

        cookies = "\n".join(
            [
                "# Netscape HTTP Cookie File",
                "# http://curl.haxx.se/rfc/cookie_spec.html",
                "# This is a generated file!  Do not edit.",
                "\n",
            ]
        )
        cookies += "\n".join("\t".join(cookie_parts) for cookie_parts in result)

        with open("cookies.txt", "w") as f:
            f.write(cookies)

    finally:
        driver.quit()

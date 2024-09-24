import os
import time
import chromedriver_autoinstaller
import selenium.webdriver.support.expected_conditions as EC

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from dotenv import load_dotenv

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
    webdriver_wait = WebDriverWait(driver, 20)

    try:
        driver.get("https://www.youtube.com")
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1

        webdriver_wait.until(
            EC.element_to_be_clickable((By.LINK_TEXT, "Sign in"))
        ).click()

        # Enter email
        webdriver_wait.until(
            EC.element_to_be_clickable((By.XPATH, '//*[@type="email"]'))
        ).send_keys(email)
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1
        driver.find_element(By.XPATH, '//*[@id="identifierNext"]').click()

        # Enter password
        webdriver_wait.until(
            EC.element_to_be_clickable((By.XPATH, '//*[@type="password"]'))
        ).send_keys(passw)
        driver.save_screenshot(f"{SCREENSHOT_PATH}/signin-{screenshot_idx}.png")
        screenshot_idx += 1
        driver.find_element(By.XPATH, '//*[@id="passwordNext"]').click()

        time.sleep(3)
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
        ) + "\n".join("\t".join(cookie_parts) for cookie_parts in result)

        with open("cookies.txt", "w") as f:
            f.write(cookies)
    except Exception as e:
        print(f"Failed to fetch cookies: {e}")
    finally:
        driver.quit()

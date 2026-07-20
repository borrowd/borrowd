import allure
import pytest
from faker import Faker
from pages.profile_page import ProfilePage

fake = Faker()


@pytest.mark.regression
@allure.feature("Profile")
@allure.title("Profile page loads and displays personal information")
@allure.severity(allure.severity_level.NORMAL)
def test_profile_loads(user_page, base_url):
    with allure.step("Navigate to profile page"):
        user_page.goto(f"{base_url}/profile/")

    with allure.step("Verify all profile form fields are visible"):
        profile = ProfilePage(user_page)
        profile.expect_opened()
        profile.open_personal_info()


@pytest.mark.regression
@allure.feature("Profile")
@allure.title("User can update their bio on the profile page")
@allure.severity(allure.severity_level.NORMAL)
def test_update_profile_bio(user_page, base_url):
    new_bio = fake.text(max_nb_chars=100)

    with allure.step("Navigate to profile page"):
        user_page.goto(f"{base_url}/profile/")
        profile = ProfilePage(user_page)
        profile.expect_opened()
        profile.open_personal_info()

    with allure.step("Update bio and submit"):
        profile.fill_bio(new_bio)
        profile.click_update()

    with allure.step("Verify bio was saved"):
        profile.expect_opened()
        profile.open_personal_info()
        profile.expect_bio_value(new_bio)

import json
import time
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient

from prompts import (
    SYSTEM_PROMPT,
    INGREDIENT_DETECTION_PROMPT,
    RECIPE_PROMPT,
    WELCOME_MESSAGE,
)


def get_secret(name):
    value = st.secrets.get(name)
    if value in (None, ""):
        raise RuntimeError(f"Missing required secret: {name}")
    return value



GEMINI_API_KEY = (st.secrets.get("GEMINI_API_KEY") or "").strip()

try:
    TWILIO_ACCOUNT_SID = get_secret("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = get_secret("TWILIO_AUTH_TOKEN")
    TWILIO_WHATSAPP_FROM = get_secret("TWILIO_WHATSAPP_FROM")
    TWILIO_CONTENT_SID = st.secrets.get("TWILIO_CONTENT_SID")
except RuntimeError as error:
    st.error(str(error))
    st.stop()

@st.cache_resource
def get_gemini_client(api_key):
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

twilio_client = get_twilio_client()
gemini_client = get_gemini_client(GEMINI_API_KEY)
MODEL_NAME = "gemini-3.8-flash"
FALLBACK_MODEL_NAMES = (
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
)


class LocalResponse:
    def __init__(self, text):
        self.text = text


def build_local_recipe(ingredients, preferences=""):
    ingredients = [item.strip() for item in ingredients if item and item.strip()]
    if not ingredients:
        ingredients = ["eggs", "rice", "onion", "tomato"]

    ingredient_text = ", ".join(ingredients)
    pref_note = "" if not preferences else f" \nDiet note: {preferences}."

    return (
        f"### Quick {ingredients[0].title()} Skillet\n"
        f"- Time: 20 minutes\n"
        f"- Difficulty: Easy\n"
        f"- Uses: {ingredient_text}\n"
        f"- Missing: None\n"
        f"- Steps:\n"
        "1. Heat a little oil in a pan.\n"
        "2. Add the ingredients and cook until softened.\n"
        "3. Season with salt, pepper, and any pantry spices you have.\n"
        "4. Stir well and cook until everything is warm and tasty.\n"
        "5. Serve hot and enjoy.\n"
        f"\nTip: Use any extra vegetables or leftovers in the same pan so nothing goes to waste.{pref_note}"
    )


def extract_error_code(error):
    for attr in ("code", "status_code", "status"):
        value = getattr(error, attr, None)
        if value is not None:
            return value
    return None


def is_model_not_available_error(error):
    text = str(error).lower()
    return (
        "not found" in text
        or "unsupported" in text
        or "not supported" in text
        or "model" in text and "not" in text
    )


@st.cache_data(show_spinner=False)
def get_available_gemini_models():
    if gemini_client is None:
        return []
    try:
        models = []
        for model in gemini_client.models.list():
            name = getattr(model, "name", str(model))
            if isinstance(name, str):
                name = name.split("/")[-1]
            supported_actions = getattr(model, "supported_actions", None)
            if name and (
                supported_actions is None
                or "generateContent" in supported_actions
            ):
                models.append(name)
        return models
    except Exception:
        return []


def get_gemini_model_candidates():
    seen = set()
    for model_name in (
        MODEL_NAME,
        *get_available_gemini_models(),
        *FALLBACK_MODEL_NAMES,
    ):
        if model_name and model_name not in seen:
            seen.add(model_name)
            yield model_name


def generate_content(contents, config=None):
    if gemini_client is None:
        if isinstance(contents, str) and "The user confirmed these ingredients" in contents:
            return LocalResponse(build_local_recipe([item.strip() for item in contents.split("The user confirmed these ingredients:", 1)[1].split("\n", 1)[0].split(",") if item.strip()]))
        raise RuntimeError("No Gemini API key is configured.")

    candidates = list(get_gemini_model_candidates())
    last_model = candidates[-1] if candidates else FALLBACK_MODEL_NAMES[-1]

    for model_name in candidates:
        try:
            return gemini_client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
        except Exception as error:
            error_code = extract_error_code(error)
            if error_code not in (429, 503) and not is_model_not_available_error(error):
                raise
            if model_name == last_model:
                raise
            st.warning(f"Gemini model '{model_name}' is unavailable or busy. Retrying with another supported model...")
            time.sleep(2)
    raise RuntimeError("Gemini request failed after retrying across supported models.")

def clean_whatsapp_text(text):
    if not text:
        return "No Recipe Found"
    text = " ".join(text.split())
    return text

def send_whatsapp(to_number, user_name, summary):
    try:
        sanitized_summary = clean_whatsapp_text(summary)
        content_variables = {
            "user_name": user_name,
            "summary": sanitized_summary,
        }

        if TWILIO_CONTENT_SID:
            message = twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:{to_number}",
                content_sid=TWILIO_CONTENT_SID,
                content_variables=content_variables,
            )
        else:
            message = twilio_client.messages.create(
                from_=TWILIO_WHATSAPP_FROM,
                to=f"whatsapp:{to_number}",
                body=f"Hi {user_name}! Here is your recipe:\n{sanitized_summary}",
            )
        return True, message.sid
    except Exception as error:
        st.error(f"Failed to send WhatsApp message ({type(error).__name__}): {error}")
        return False, None

def render_message(message):
    with st.chat_message(message["role"]): 
        if message["kind"] == "text":
            st.markdown(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])    



def add_message(role,kind,content):
    st.session_state.messages.append({"role":role,"kind":kind,"content":content})
    render_message(st.session_state.messages[-1])

if "onboarded" not in st.session_state:
    st.session_state.onboarded = False

if not st.session_state.onboarded:
    st.title("Fridge to Recipe 🥗")
    st.caption(
        "Tell me a little about yourself, then share a photo of your fridge "
        "or pantry. We'll find something good to make."
    )
    with st.form("onboarding_form"):
        username = st.text_input("What's your name?", key="username")
        phone_number = st.text_input("What's your phone number?", key="phone_number")
        preferences = st.text_area(
            "Any food allergies or dietary preferences I should keep in mind?",
            key="preferences",
        )
        submitted = st.form_submit_button("Let's get cooking")

    if submitted:
        username = username.strip()
        phone_number = phone_number.strip()
        preferences = preferences.strip()
        if not username or not phone_number or not preferences:
            st.error("Please fill in all fields to get started.")
        else:
            st.session_state.profile_name = username
            st.session_state.whatsapp_phone_number = phone_number
            st.session_state.user_preferences = preferences
            st.session_state.messages = []
            st.session_state.onboarded = True
            st.rerun()
    st.stop()

st.title("Fridge to Recipe 🥗")
st.caption("Upload a clear photo and I'll help you figure out what to cook.")

uploaded_file = st.file_uploader(
    "Choose a fridge or pantry photo",
    type=["jpg", "jpeg", "png", "webp"],
)

if "manual_ingredients_mode" not in st.session_state:
    st.session_state.manual_ingredients_mode = False

if uploaded_file and st.button("Identify ingredients"):
    if gemini_client is None:
        st.session_state.manual_ingredients_mode = True
        st.session_state.detected_ingredients = []
        st.session_state.uncertain_ingredients = []
        st.session_state.confirmed_ingredients = ""
        st.info("No AI provider is configured. Enter the ingredients manually below and I’ll still suggest recipes.")
    else:
        with st.spinner("Taking a closer look at your photo..."):
            try:
                response = generate_content(
                    contents=[
                        INGREDIENT_DETECTION_PROMPT,
                        types.Part.from_bytes(
                            data=uploaded_file.getvalue(),
                            mime_type=uploaded_file.type or "image/jpeg",
                        ),
                    ],
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                detected = json.loads(response.text or "{}")
                ingredients = detected.get("ingredients", [])
                uncertain = detected.get("uncertain", [])
                if not isinstance(ingredients, list) or not isinstance(uncertain, list):
                    raise ValueError("The ingredient response had an unexpected format.")
                st.session_state.detected_ingredients = ingredients
                st.session_state.uncertain_ingredients = uncertain
                st.session_state.confirmed_ingredients = ", ".join(ingredients)
                st.session_state.manual_ingredients_mode = False
            except Exception as error:
                error_code = extract_error_code(error)
                if error_code in (429, 503):
                    st.error(
                        "The AI image analysis is temporarily unavailable because Gemini quota or service capacity was reached. "
                        "Please try again in a few minutes, or switch to a different Google AI plan and model."
                    )
                elif error_code in (401, "401") or "access_token_type_unsupported" in str(error).lower():
                    st.error(
                        "Gemini rejected its credentials. Set GEMINI_API_KEY to a valid "
                        "Gemini Developer API key from Google AI Studio, not an OAuth access token. "
                        "You can enter ingredients manually below."
                    )
                else:
                    st.error(f"Photo analysis failed ({type(error).__name__}): {error}")
                st.session_state.manual_ingredients_mode = True
                st.session_state.confirmed_ingredients = ""

if "detected_ingredients" in st.session_state or st.session_state.get("manual_ingredients_mode"):
    if st.session_state.get("manual_ingredients_mode"):
        ingredients_text = st.text_area(
            "Type ingredients separated by commas",
            key="manual_ingredients_text",
            value=st.session_state.get("confirmed_ingredients", ""),
        )
        if st.button("Suggest recipes", type="primary"):
            ingredients = [item.strip() for item in ingredients_text.split(",") if item.strip()]
            if not ingredients:
                st.error("Add at least one ingredient to get recipe ideas.")
            else:
                recipe = build_local_recipe(ingredients, st.session_state.user_preferences)
                st.session_state.messages = [{"role": "assistant", "kind": "text", "category": "recipe", "content": recipe}]
    else:
        uncertain = st.session_state.uncertain_ingredients
        if uncertain:
            st.info("I'm not sure about: " + ", ".join(uncertain))

        ingredients_text = st.text_area(
            "Check the ingredients and edit the list if needed",
            key="confirmed_ingredients",
        )
        if st.button("Suggest recipes", type="primary"):
            ingredients = [item.strip() for item in ingredients_text.split(",") if item.strip()]
            if not ingredients:
                st.error("Add at least one ingredient to get recipe ideas.")
            else:
                with st.spinner("Finding a few good things to make..."):
                    try:
                        recipe_response = generate_content(
                            contents=RECIPE_PROMPT.format(
                                ingredients=", ".join(ingredients),
                                preferences=st.session_state.user_preferences,
                            ),
                            config=types.GenerateContentConfig(
                                system_instruction=SYSTEM_PROMPT
                            ),
                        )
                        recipe = (recipe_response.text or "").strip()
                        if not recipe:
                            st.error("I couldn't come up with a recipe just now. Please try again.")
                        else:
                            st.session_state.messages = [
                                {
                                    "role": "assistant",
                                    "kind": "text",
                                    "category": "recipe",
                                    "content": recipe,
                                }
                            ]
                    except Exception as error:
                        st.warning(
                            f"Recipe generation failed ({type(error).__name__}); "
                            "showing a local suggestion instead."
                        )
                        recipe = build_local_recipe(
                            ingredients, st.session_state.user_preferences
                        )
                        st.session_state.messages = [{
                            "role": "assistant",
                            "kind": "text",
                            "category": "recipe",
                            "content": recipe,
                        }]

messages = st.session_state.get("messages", [])
assistant_messages = [
    message["content"]
    for message in messages
    if message.get("role") == "assistant"
    and message.get("category") == "recipe"
    and message.get("content")
]

if assistant_messages:
    latest_message = assistant_messages[-1]
    st.subheader("Recipe ideas")
    st.markdown(latest_message)
    whatsapp_url = f"https://wa.me/?text={quote(latest_message, safe='')}"
    st.link_button("Send latest recipe via WhatsApp", whatsapp_url)
else:
    st.button("Send latest recipe via WhatsApp", disabled=True)

profile_name = st.session_state.get("profile_name", "Guest")
phone_number = st.session_state.get("whatsapp_phone_number", "not set")
st.caption(
    f"Logged in as {profile_name} - "
    f"updates go to {phone_number}"
)

if not messages:
    add_message("assistant", "text", WELCOME_MESSAGE)
else:
    for message in messages:
        render_message(message)
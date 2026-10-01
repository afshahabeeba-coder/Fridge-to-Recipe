import json
from urllib.parse import quote

import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient
from prompts import (
    
    SYSTEM_PROMPT,
    INGREDIENT_DETECTION_PROMPT,
    RECIPE_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE,
)

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM  = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID  = st.secrets["TWILIO_CONTENT_SID"]




@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

twilio_client = get_twilio_client()
gemini_client = get_gemini_client()
MODEL_NAME = "gemini-3.8-flash"
FALLBACK_MODEL_NAME = "gemini-3.5-flash"


def generate_content(contents, config=None):
    try:
        return gemini_client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=config,
        )
    except Exception as error:
        if getattr(error, "code", None) != 503:
            raise
        return gemini_client.models.generate_content(
            model=FALLBACK_MODEL_NAME,
            contents=contents,
            config=config,
        )

def clean_whatsapp_text(text):
    if not text:
        return "No Recipe Found"
    text = " ".join(text.split())
    return text

def send_whatsapp(to_number,user_name,summary):
   try:
       content_variable = json.dumps({"user_name": user_name, "summary": summary})

       message = twilio_client.messages.create(
           from_=TWILIO_WHATSAPP_FROM,
           to=f"whatsapp:{to_number}",
           content_sid=TWILIO_CONTENT_SID,
           body=content_variable
       )
       return True,message.sid
   except Exception as error:
       st.error(f"Failed to send WhatsApp message ({type(error).__name__}): {error}")

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

if uploaded_file and st.button("Identify ingredients"):
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
        except Exception as error:
            st.error(f"Photo analysis failed ({type(error).__name__}): {error}")

if "detected_ingredients" in st.session_state:
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
                    st.error(f"Recipe generation failed ({type(error).__name__}): {error}")

assistant_messages = [
    message["content"]
    for message in st.session_state.get("messages", [])
    if message.get("role") == "assistant"
    and message.get("category") == "recipe"
    and message.get("content")
]

if assistant_messages:
    latest_message = assistant_messages[-1]
    st.subheader("Recipe ideas")
    st.markdown(latest_message)
    phone_digits = "".join(
        character
        for character in st.session_state.whatsapp_phone_number
        if character.isdigit()
    )
    if phone_digits:
        whatsapp_url = f"https://wa.me/{phone_digits}?text={quote(latest_message, safe='')}"
        st.link_button("Send latest recipe via WhatsApp", whatsapp_url)
    else:
        st.warning("Add a valid phone number, including its country code, to open WhatsApp.")
else:
    st.button("Send latest recipe via WhatsApp", disabled=True)
st.caption(
    f"Logged in as {st.session_state.profile_name} - "
    f"updates go to {st.session_state.whatsapp_phone_number}"
)
if not st.session_state.messages:
    add_message("assistant", "text",WELCOME_MESSAGE)
else:
    for message in st.session_state.messages:
        render_message(message)
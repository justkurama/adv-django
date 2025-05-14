from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django import forms
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAI
from llama_index.core import SimpleDirectoryReader
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import os
import json
import numpy as np
from .models import ChatSession, ChatMessage, UserProfile
from django.db import transaction
from allauth.socialaccount.models import SocialAccount
from django.core.mail import send_mail
from django.utils.crypto import get_random_string
from django.contrib import messages

# Define the prompt and model
prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a highly experienced and trusted medical doctor. Always respond with clinical accuracy, clarity, and empathy. "
            "Provide helpful, detailed explanations when needed, but avoid making a definitive diagnosis without sufficient information. "
            "If a question requires an in-person examination or urgent attention, clearly state that."
        ),
        (
            "user",
            "Patient's question or symptom: {question}\n\nRelevant context (if any): {context}"
        )
    ]
)
llm = OpenAI(api_key=settings.OPENAI_API_KEY)
chain = prompt | llm
embedding_model = SentenceTransformer('sentence-transformers/paraphrase-MiniLM-L6-v2')

def get_document_embeddings(documents):
    embeddings = embedding_model.encode([document.text for document in documents])
    return np.array(embeddings)

def find_similar_documents(query, documents, doc_embeddings):
    query_embedding = embedding_model.encode([query]).reshape(1, -1)
    similarities = cosine_similarity(query_embedding, doc_embeddings).flatten()
    ranked_indices = similarities.argsort()[::-1]
    return [documents[i] for i in ranked_indices[:5]]

def perform_rag_query(documents, query):
    if not documents:
        return ""
    doc_embeddings = get_document_embeddings(documents)
    similar_docs = find_similar_documents(query, documents, doc_embeddings)
    context = "\n\n".join([doc.text for doc in similar_docs])
    return context

@login_required
def index(request):
    profile_picture_url = None
    # Prefer our UserProfile image if exists
    if hasattr(request.user, 'profile') and request.user.profile.profile_image:
        profile_picture_url = request.user.profile.profile_image.url
    else:
        # fallback to social account (google) if exists
        social_account = SocialAccount.objects.filter(user=request.user, provider='google').first()
        if social_account:
            profile_picture_url = social_account.extra_data.get('picture')

    # Fetch all chat sessions for the logged-in user
    sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
    session = None
    session_id = request.GET.get('session_id')
    new_session = request.GET.get('new_session')
    delete_session = request.GET.get('delete_session')

    # Delete chat session and its messages
    if request.method == 'POST' and delete_session:
        session_to_delete = get_object_or_404(ChatSession, id=delete_session, user=request.user)
        session_to_delete.delete()
        sessions = ChatSession.objects.filter(user=request.user).order_by('-created_at')
        chat_sessions = []
        for i, s in enumerate(sessions):
            first_msg = s.messages.order_by('timestamp').first()
            chat_sessions.append({
                "id": s.id,
                "title": s.title or f"Chat {i+1}",
                "first_query": first_msg.content[:32] if first_msg else ""
            })
        return JsonResponse({"chat_sessions": chat_sessions})

    if new_session:
        session = ChatSession.objects.create(user=request.user, title=f"Chat {sessions.count() + 1}")
        chat_messages = []
        show_suggestions = True
    elif session_id:
        session = get_object_or_404(ChatSession, id=session_id, user=request.user)
        show_suggestions = session.messages.count() == 0
    else:
        session = sessions.first()
        show_suggestions = session.messages.count() == 0 if session else True

    # AJAX: Return chat messages for a session
    if request.method == 'GET' and (session_id or new_session):
        chat_messages = [
            {
                "role": msg.sender,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat()
            }
            for msg in session.messages.order_by('timestamp')
        ] if session else []
        chat_sessions = []
        for i, s in enumerate(sessions):
            first_msg = s.messages.order_by('timestamp').first()
            chat_sessions.append({
                "id": s.id,
                "title": s.title or f"Chat {i+1}",
                "first_query": first_msg.content[:32] if first_msg else ""
            })
        return JsonResponse({
            "chat_messages": chat_messages,
            "session_id": session.id if session else None,
            "chat_sessions": chat_sessions,
        })

    # For initial page load
    chat_messages = [
        {
            "role": msg.sender,
            "content": msg.content,
            "timestamp": msg.timestamp.isoformat()
        }
        for msg in session.messages.order_by('timestamp')
    ] if session else []
    chat_sessions = []
    for i, s in enumerate(sessions):
        first_msg = s.messages.order_by('timestamp').first()
        chat_sessions.append({
            "id": s.id,
            "title": s.title or f"Chat {i+1}",
            "first_query": first_msg.content[:32] if first_msg else ""
        })
    # Get user initial for fallback
    user_initial = (request.user.get_full_name() or request.user.username or "U")[0].upper()

    context = {
        'profile_picture_url': profile_picture_url,
        'chat_messages': chat_messages,
        'show_suggestions': show_suggestions,
        'suggestions': [
            "What are common symptoms of diabetes?",
            "How can I manage high blood pressure?",
            "What is the normal range for blood sugar?",
            "What are the side effects of paracetamol?",
            "How do I treat a minor burn at home?",
            "What is the difference between a cold and the flu?",
            "When should I see a doctor for a headache?",
            "What vaccines are recommended for adults?",
            "How can I improve my sleep quality?",
            "What are the warning signs of a heart attack?"
        ],
        'user': request.user,
        'session_id': session.id if session else None,
        'chat_sessions': chat_sessions,
        'user_initial': user_initial,
    }

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            message = data.get('message', '')
            session_id_post = data.get('session_id')
            # Try to get session, if not found, create a new one for the user
            session = ChatSession.objects.filter(id=session_id_post, user=request.user).first()
            if not session:
                session = ChatSession.objects.create(user=request.user, title=f"Chat {ChatSession.objects.filter(user=request.user).count() + 1}")
            documents = []
            temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploaded_files')
            if os.path.exists(temp_dir) and os.listdir(temp_dir):
                documents = SimpleDirectoryReader(temp_dir).load_data()
            context_rag = perform_rag_query(documents, message) if documents else ""
            # Defensive: ensure message is not empty
            if not message.strip():
                return JsonResponse({'response': "Please enter a valid question."})
            try:
                # Ensure the LLM call does not raise or return None
                response = chain.invoke({"question": message, "context": context_rag})
                if not response:
                    response = "Sorry, I couldn't process your request at the moment."
            except Exception as e:
                # Log the error for debugging
                import traceback
                print("AI error:", traceback.format_exc())
                response = "Sorry, I couldn't process your request at the moment."
            # Save user message
            ChatMessage.objects.create(
                session=session,
                sender='user',
                content=message,
                extra_data={}
            )
            # Save assistant message
            ChatMessage.objects.create(
                session=session,
                sender='assistant',
                content=str(response),
                extra_data={}
            )
            return JsonResponse({'response': str(response)})
        except Exception as e:
            # Log the error for debugging
            import traceback
            print("POST error:", traceback.format_exc())
            return JsonResponse({'response': "Sorry, something went wrong. Please try again later."}, status=200)

    return render(request, 'admin_view/index.html', context)
def upload_files(request):
    if request.method == 'POST':
        try:
            uploaded_files = request.FILES.getlist('uploaded_files')
            temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploaded_files')

            # Create the temporary directory if it doesn't exist
            os.makedirs(temp_dir, exist_ok=True)

            for uploaded_file in uploaded_files:
                file_path = os.path.join(temp_dir, uploaded_file.name)
                with open(file_path, 'wb') as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
            
            return JsonResponse({'status': 'success', 'message': 'Files uploaded successfully'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'File upload failed: {e}'}, status=500)
    return JsonResponse({'status': 'error', 'message': 'Invalid request method'}, status=405)

def logout_view(request):
    logout(request)
    return redirect('/')

class CustomUserCreationForm(UserCreationForm):
    email = forms.EmailField(required=True)
    photo = forms.ImageField(required=False)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2", "photo")

    def clean_email(self):
        email = self.cleaned_data.get("email")
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("A user with that username already exists.")
        return username

def signup(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                user = form.save(commit=False)
                user.save()
                photo = form.cleaned_data.get('photo')
                profile = UserProfile.objects.create(user=user)
                if photo:
                    profile.profile_image = photo
                    profile.save()
            backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user, backend=backend)
            return redirect('index')
    else:
        form = CustomUserCreationForm()
    return render(request, 'account/signup.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect('index')
    else:
        form = AuthenticationForm()
    return render(request, 'account/login.html', {'form': form})

class PasswordResetForm(forms.Form):
    email = forms.EmailField(label="Email", required=True)

class OTPForm(forms.Form):
    otp = forms.CharField(label="OTP", max_length=6, required=True)
    new_password1 = forms.CharField(label="New Password", widget=forms.PasswordInput, required=True)
    new_password2 = forms.CharField(label="Confirm Password", widget=forms.PasswordInput, required=True)

def forgot_password(request):
    if request.method == 'POST':
        form = PasswordResetForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            user = User.objects.filter(email__iexact=email).first()
            if user:
                otp = get_random_string(6, allowed_chars='0123456789')
                request.session['reset_email'] = email
                request.session['reset_otp'] = otp
                send_mail(
                    'Your OTP for Password Reset',
                    f'Your OTP is: {otp}',
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=False,
                )
                return redirect('verify_otp')
            else:
                messages.error(request, "No user found with this email.")
    else:
        form = PasswordResetForm()
    return render(request, 'account/forgot_password.html', {'form': form})

def verify_otp(request):
    email = request.session.get('reset_email')
    otp_session = request.session.get('reset_otp')
    if not email or not otp_session:
        return redirect('forgot_password')
    if request.method == 'POST':
        form = OTPForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            new_password1 = form.cleaned_data['new_password1']
            new_password2 = form.cleaned_data['new_password2']
            if otp != otp_session:
                messages.error(request, "Invalid OTP.")
            elif new_password1 != new_password2:
                messages.error(request, "Passwords do not match.")
            else:
                user = User.objects.filter(email__iexact=email).first()
                if user:
                    user.set_password(new_password1)
                    user.save()
                    # Clean up session
                    request.session.pop('reset_email', None)
                    request.session.pop('reset_otp', None)
                    messages.success(request, "Password reset successful. You can now log in.")
                    return redirect('login')
                else:
                    messages.error(request, "User not found.")
    else:
        form = OTPForm()
    return render(request, 'account/verify_otp.html', {'form': form, 'email': email})

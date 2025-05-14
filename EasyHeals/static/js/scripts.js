document.addEventListener('DOMContentLoaded', function() {
    const darkModeToggle = document.querySelector('#dark-mode-toggle');
    const chatInput = document.querySelector('#chat-input');
    const attachButton = document.querySelector('#attach-button');
    const fileInput = document.querySelector('#file-input');
    const sidebar = document.querySelector('#sidebar');
    const sidebarToggle = document.querySelector('#sidebar-toggle');
    const sidebarClose = document.querySelector('#sidebar-close');
    const documentList = document.querySelector('#document-list');
    const chatForm = document.querySelector('#chat-form');
    const chatMessages = document.getElementById('chat-messages');
    const chatHistoryList = document.getElementById('chat-history-list');
    const newChatBtn = document.getElementById('new-chat-btn');
    let chatSessions = window.CHAT_SESSIONS || [];
    let currentSessionId = window.CURRENT_SESSION_ID;
    let chatMessagesData = window.CHAT_MESSAGES || [];
    const userInitial = window.USER_INITIAL || 'U';
    const profilePictureUrl = window.PROFILE_PICTURE_URL || '';
    const assistantImageUrl = '/static/images/AI.jpg';
    const chatSessionUrl = window.CHAT_SESSION_URL;
    const chatPostUrl = window.CHAT_POST_URL;

    // Dark mode toggle
    darkModeToggle.addEventListener('click', () => {
        document.body.classList.toggle('dark-mode');
    });

    // File input for attachments
    attachButton.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', (event) => {
        const files = event.target.files;
        displayUploadedFiles(files);
        uploadFiles(files);
    });

    // Render chat messages
    function renderChatMessages(messages) {
        chatMessages.innerHTML = '';
        messages.forEach(msg => {
            const row = document.createElement('div');
            row.className = `chat-bubble-row ${msg.role}`;
            if (msg.role === 'assistant') {
                // AI avatar: show image if exists, else show initials "AI"
                row.innerHTML = `
                    ${assistantImageUrl ? `<img src="${assistantImageUrl}" class="profile-image me-2" alt="AI">` : `<div class="ai-initial me-2">AI</div>`}
                    <div class="chat-bubble assistant">${msg.content}</div>
                `;
            } else {
                // User avatar: show image if exists, else show initial
                row.innerHTML = `
                    <div class="chat-bubble user">${msg.content}</div>
                    ${profilePictureUrl
                        ? `<img src="${profilePictureUrl}" class="profile-image ms-2" alt="User">`
                        : `<div class="profile-initial ms-2">${userInitial}</div>`
                    }
                `;
            }
            chatMessages.appendChild(row);
        });
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    // Render chat history
    function renderChatHistory(sessions, activeSessionId) {
        chatHistoryList.innerHTML = '';
        sessions.forEach(session => {
            const btn = document.createElement('div');
            btn.className = 'd-flex align-items-center justify-content-between chat-history-item' + (session.id === activeSessionId ? ' active' : '');
            btn.dataset.sessionId = session.id;

            // Truncate first query for display
            let displayText = session.first_query ? session.first_query : (session.title || `Chat ${session.id}`);
            if (displayText.length > 32) displayText = displayText.slice(0, 32) + '...';

            // Chat session click
            const chatBtn = document.createElement('button');
            chatBtn.className = 'flex-grow-1 text-start border-0 bg-transparent p-0 m-0';
            chatBtn.style.outline = 'none';
            chatBtn.innerText = displayText;
            chatBtn.addEventListener('click', function(e) {
                if (currentSessionId !== session.id) {
                    loadChatSession(session.id);
                }
            });

            // Trash icon for delete
            const trashBtn = document.createElement('button');
            trashBtn.className = 'btn btn-link text-danger p-0 ms-2';
            trashBtn.innerHTML = '<i class="bi bi-trash"></i>';
            trashBtn.title = 'Delete chat';
            trashBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                if (confirm('Delete this chat and all its messages?')) {
                    deleteChatSession(session.id);
                }
            });

            btn.appendChild(chatBtn);
            btn.appendChild(trashBtn);
            chatHistoryList.appendChild(btn);
        });
    }

    // Delete chat session
    function deleteChatSession(sessionId) {
        fetch(`${chatSessionUrl}?delete_session=${sessionId}`, { method: 'POST', headers: { 'X-CSRFToken': getCookie('csrftoken') } })
            .then(res => res.json())
            .then(data => {
                chatSessions = data.chat_sessions;
                // If deleted session was active, switch to first available
                if (currentSessionId == sessionId) {
                    if (chatSessions.length > 0) {
                        currentSessionId = chatSessions[0].id;
                        loadChatSession(currentSessionId);
                    } else {
                        currentSessionId = null;
                        renderChatMessages([]);
                    }
                }
                renderChatHistory(chatSessions, currentSessionId);
            });
    }

    // Hide suggestions bar
    function hideSuggestionsBar() {
        const suggestionsBar = document.querySelector('.suggestions-bar');
        if (suggestionsBar) suggestionsBar.style.display = 'none';
    }

    // Load chat session
    function loadChatSession(sessionId) {
        fetch(`${chatSessionUrl}?session_id=${sessionId}`)
            .then(res => res.json())
            .then(data => {
                currentSessionId = sessionId;
                chatMessagesData = data.chat_messages;
                renderChatMessages(chatMessagesData);
                renderChatHistory(chatSessions, currentSessionId);
                // Show suggestions only if no messages
                if (chatMessagesData.length === 0) {
                    const suggestionsBar = document.querySelector('.suggestions-bar');
                    if (suggestionsBar) suggestionsBar.style.display = '';
                } else {
                    hideSuggestionsBar();
                }
            });
    }

    // Initial render
    renderChatMessages(chatMessagesData);
    renderChatHistory(chatSessions, currentSessionId);
    // Hide suggestions if there are already messages
    if (chatMessagesData.length > 0) hideSuggestionsBar();

    // New Chat button
    newChatBtn.addEventListener('click', function() {
        fetch(`${chatSessionUrl}?new_session=1`)
            .then(res => res.json())
            .then(data => {
                currentSessionId = data.session_id;
                chatSessions = data.chat_sessions;
                chatMessagesData = [];
                renderChatMessages([]);
                renderChatHistory(chatSessions, currentSessionId);
                // Show suggestions for new chat
                const suggestionsBar = document.querySelector('.suggestions-bar');
                if (suggestionsBar) suggestionsBar.style.display = '';
            });
    });

    // Send message using form submit
    chatForm.addEventListener('submit', function(e) {
        e.preventDefault();
        const message = chatInput.value.trim();
        if (message !== '') {
            // User bubble immediately
            const userDiv = document.createElement('div');
            userDiv.className = 'chat-bubble-row user';
            userDiv.innerHTML = `
                <div class="chat-bubble user">${message}</div>
                ${profilePictureUrl
                    ? `<img src="${profilePictureUrl}" class="profile-image ms-2" alt="User">`
                    : `<div class="profile-initial ms-2">${userInitial}</div>`
                }
            `;
            chatMessages.appendChild(userDiv);

            // AI bubble with loader
            const aiDiv = document.createElement('div');
            aiDiv.className = 'chat-bubble-row assistant';
            aiDiv.innerHTML = `
                ${assistantImageUrl
                    ? `<img src="${assistantImageUrl}" class="profile-image me-2" alt="AI">`
                    : `<div class="ai-initial me-2">AI</div>`
                }
                <div class="chat-bubble assistant"><span class="dots-loader"><span></span><span></span><span></span></span></div>
            `;
            chatMessages.appendChild(aiDiv);
            chatMessages.scrollTop = chatMessages.scrollHeight;

            // Hide suggestions after first query
            hideSuggestionsBar();

            fetch(chatPostUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ message, session_id: currentSessionId })
            })
            .then(response => response.json())
            .then(data => {
                // Replace loader with actual response in the same AI bubble
                const aiBubble = aiDiv.querySelector('.chat-bubble.assistant');
                if (aiBubble) {
                    aiBubble.innerHTML = data.response;
                }
                chatInput.value = '';
                chatMessages.scrollTop = chatMessages.scrollHeight;
            })
            .catch(() => {
                const aiBubble = aiDiv.querySelector('.chat-bubble.assistant');
                if (aiBubble) {
                    aiBubble.innerHTML = '<span class="text-danger">Error loading response.</span>';
                }
            });
        }
    });

    // Sidebar toggle functionality
    sidebarToggle.addEventListener('click', () => {
        sidebar.classList.toggle('hidden');
    });

    sidebarClose.addEventListener('click', () => {
        sidebar.classList.add('hidden');
    });

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function displayUploadedFiles(files) {
        documentList.innerHTML = ''; // Clear previous list
        Array.from(files).forEach(file => {
            const fileItem = document.createElement('div');
            fileItem.classList.add('file-item');
            fileItem.dataset.fileName = file.name;

            const fileName = document.createElement('span');
            fileName.textContent = `${file.name} (${Math.round(file.size / 1024)} KB)`;

            const removeButton = document.createElement('button');
            removeButton.textContent = 'X';
            removeButton.addEventListener('click', () => {
                fileItem.remove();
            });

            fileItem.appendChild(fileName);
            fileItem.appendChild(removeButton);
            documentList.appendChild(fileItem);
        });
    }

    function uploadFiles(files) {
        const formData = new FormData();
        Array.from(files).forEach(file => {
            formData.append('uploaded_files', file);
        });

        fetch('/upload-files/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            console.log('Files uploaded successfully:', data);
        })
        .catch(() => {
            console.error('Error uploading files');
        });
    }
    
});

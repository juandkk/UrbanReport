// Feed Comunitario Interactions (Vistas 4 y 5)
document.addEventListener('DOMContentLoaded', () => {
  // CSRF token helper
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
  const csrftoken = getCookie('csrftoken');

  // Likes handling
  document.querySelectorAll('.action-like-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const postId = btn.getAttribute('data-post-id');
      if (!postId) return;

      try {
        const response = await fetch(`/feed/like/${postId}/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'Content-Type': 'application/json'
          }
        });
        if (response.ok) {
          const data = await response.json();
          const countSpan = btn.querySelector('.like-count');
          if (countSpan) {
            countSpan.textContent = data.likes;
            btn.style.color = '#3b82f6';
          }
        }
      } catch (err) {
        console.error('Error al dar like:', err);
      }
    });
  });

  // Modal inspection handling (for eye/target and info icons)
  const inspectModal = document.getElementById('inspectModal');
  const modalCloseBtn = document.querySelector('.close-modal-btn');
  const modalTitle = document.getElementById('modalIncidentTitle');
  const modalLocation = document.getElementById('modalIncidentLocation');
  const modalStatus = document.getElementById('modalIncidentStatus');

  document.querySelectorAll('.action-inspect').forEach(btn => {
    btn.addEventListener('click', () => {
      const title = btn.getAttribute('data-title') || 'Detalle de Incidencia';
      const location = btn.getAttribute('data-location') || 'Ubicación reportada';
      const status = btn.getAttribute('data-status') || 'REPORTADO';

      if (modalTitle) modalTitle.textContent = title;
      if (modalLocation) modalLocation.textContent = location;
      if (modalStatus) {
        modalStatus.textContent = status;
        modalStatus.className = 'status-badge ' + status.toLowerCase();
      }

      if (inspectModal) inspectModal.classList.add('active');
    });
  });

  if (modalCloseBtn && inspectModal) {
    modalCloseBtn.addEventListener('click', () => {
      inspectModal.classList.remove('active');
    });
    inspectModal.addEventListener('click', (e) => {
      if (e.target === inspectModal) {
        inspectModal.classList.remove('active');
      }
    });
  }

  // Quick Composer Modal / Trigger
  const composerInput = document.querySelector('.composer-input-btn');
  const postModal = document.getElementById('newPostModal');
  const postModalClose = document.querySelector('.close-post-modal-btn');

  if (composerInput && postModal) {
    composerInput.addEventListener('click', () => {
      postModal.classList.add('active');
      const textarea = postModal.querySelector('textarea');
      if (textarea) textarea.focus();
    });
  }

  if (postModalClose && postModal) {
    postModalClose.addEventListener('click', () => {
      postModal.classList.remove('active');
    });
    postModal.addEventListener('click', (e) => {
      if (e.target === postModal) {
        postModal.classList.remove('active');
      }
    });
  }
});

/**
 * UrbanReport - Feed Comunitario (Interacciones avanzadas)
 * Reacciones Like/Dislike únicas por usuario, comentarios y respuestas anidadas,
 * moderación para administradores (Censurar / Eliminar) y reportes para usuarios.
 */

document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  // ── Helper para obtener Cookie CSRF ──
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

  const portalWrapper = document.querySelector('.portal-wrapper');
  const userRol = portalWrapper ? portalWrapper.dataset.userRol : '';
  const isAdmin = userRol === 'ADMINISTRADOR';

  // ── Helper Notificaciones Toast ──
  function showToast(msg, isError = false) {
    const toast = document.getElementById('urbanToast');
    const toastMsg = document.getElementById('urbanToastMsg');
    const toastIcon = document.getElementById('urbanToastIcon');
    if (!toast || !toastMsg) return;

    toastMsg.textContent = msg;
    if (toastIcon) {
      toastIcon.textContent = isError ? '✕' : '✓';
      toastIcon.style.background = isError ? '#ef4444' : '#10b981';
    }
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), 3500);
  }

  // ── Abrir la publicación en su vista de detalle al hacer clic en el contenido ──
  document.addEventListener('click', (e) => {
    const content = e.target.closest('.post-clickable');
    if (!content) return;
    // No navegar si el clic fue sobre un elemento interactivo (botones, enlaces, imágenes con su propio manejo)
    if (e.target.closest('a, button, input, textarea, .post-menu-wrapper')) return;
    const url = content.dataset.detailUrl;
    if (url) window.location.href = url;
  });

  // ── Reposteo (toggle estilo Twitter/X) ──
  document.addEventListener('click', async (e) => {
    const repostBtn = e.target.closest('.action-repost-btn');
    if (!repostBtn) return;
    e.preventDefault();
    const postId = repostBtn.dataset.postId;
    if (!postId || repostBtn.disabled) return;
    repostBtn.disabled = true;
    try {
      const res = await fetch(`/feed/publicacion/${postId}/repost/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken, 'X-Requested-With': 'XMLHttpRequest' },
      });
      const data = await res.json();
      if (data.status === 'ok') {
        repostBtn.classList.toggle('active', data.reposteado);
        const count = repostBtn.querySelector('.repost-count');
        if (count) count.textContent = data.total_reposteos;
        showToast(data.message);
      }
    } catch (err) {
      console.error('Error al repostear:', err);
      showToast('Error al repostear', true);
    } finally {
      repostBtn.disabled = false;
    }
  });

  // ── Menú de 3 puntos de comentarios (abrir/cerrar) ──
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.comment-menu-trigger');
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      const commentId = trigger.dataset.commentId;
      const dropdown = document.getElementById(`comment-menu-dropdown-${commentId}`);
      document.querySelectorAll('.comment-menu-dropdown.show').forEach(d => {
        if (d !== dropdown) d.classList.remove('show');
      });
      if (dropdown) dropdown.classList.toggle('show');
      return;
    }
    // Cerrar al hacer clic fuera o al elegir una opción del menú
    if (!e.target.closest('.comment-menu-dropdown')) {
      document.querySelectorAll('.comment-menu-dropdown.show').forEach(d => d.classList.remove('show'));
    } else if (e.target.closest('.comment-menu-item')) {
      document.querySelectorAll('.comment-menu-dropdown.show').forEach(d => d.classList.remove('show'));
    }
  });

  // ── 1. Reacciones en Publicaciones (Like / Dislike) ──
  document.addEventListener('click', async (e) => {
    const reactBtn = e.target.closest('.action-react-btn');
    if (!reactBtn) return;

    e.preventDefault();
    const postId = reactBtn.dataset.postId;
    const tipo = reactBtn.dataset.type; // 'LIKE' o 'DISLIKE'
    if (!postId || !tipo) return;

    const postCard = document.getElementById(`post-card-${postId}`);
    const likeBtn = postCard ? postCard.querySelector('.post-like-btn') : null;
    const dislikeBtn = postCard ? postCard.querySelector('.post-dislike-btn') : null;

    try {
      const formData = new FormData();
      formData.append('tipo', tipo);

      const res = await fetch(`/feed/publicacion/${postId}/reaccionar/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      if (!res.ok) throw new Error('Error al reaccionar');
      const data = await res.json();

      if (data.status === 'ok') {
        if (likeBtn) {
          const count = likeBtn.querySelector('.like-count');
          if (count) count.textContent = data.likes;
          if (data.user_reaction === 'LIKE') {
            likeBtn.classList.add('active');
          } else {
            likeBtn.classList.remove('active');
          }
        }

        if (dislikeBtn) {
          const count = dislikeBtn.querySelector('.dislike-count');
          if (count) count.textContent = data.dislikes;
          if (data.user_reaction === 'DISLIKE') {
            dislikeBtn.classList.add('active');
          } else {
            dislikeBtn.classList.remove('active');
          }
        }
      }
    } catch (err) {
      console.error('Error en reacción de publicación:', err);
    }
  });

  // ── 2. Reacciones en Comentarios y Respuestas (Like / Dislike) ──
  document.addEventListener('click', async (e) => {
    const comReactBtn = e.target.closest('.comment-act-btn[data-comment-id]');
    if (!comReactBtn || comReactBtn.classList.contains('comment-reply-trigger') ||
        comReactBtn.classList.contains('comment-menu-trigger') ||
        comReactBtn.classList.contains('btn-action-censor-comment') ||
        comReactBtn.classList.contains('btn-action-delete-comment') ||
        comReactBtn.classList.contains('btn-action-report-comment')) return;

    e.preventDefault();
    const commentId = comReactBtn.dataset.commentId;
    const tipo = comReactBtn.dataset.type; // 'LIKE' o 'DISLIKE'
    if (!commentId || !tipo) return;

    const commentCard = document.getElementById(`comment-card-${commentId}`);
    const likeBtn = commentCard ? commentCard.querySelector(`.comment-like-btn[data-comment-id="${commentId}"]`) : null;
    const dislikeBtn = commentCard ? commentCard.querySelector(`.comment-dislike-btn[data-comment-id="${commentId}"]`) : null;

    try {
      const formData = new FormData();
      formData.append('tipo', tipo);

      const res = await fetch(`/feed/comentario/${commentId}/reaccionar/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      if (!res.ok) throw new Error('Error al reaccionar a comentario');
      const data = await res.json();

      if (data.status === 'ok') {
        if (likeBtn) {
          const count = likeBtn.querySelector('.com-like-count');
          if (count) count.textContent = data.likes;
          if (data.user_reaction === 'LIKE') {
            likeBtn.classList.add('active');
          } else {
            likeBtn.classList.remove('active');
          }
        }

        if (dislikeBtn) {
          const count = dislikeBtn.querySelector('.com-dislike-count');
          if (count) count.textContent = data.dislikes;
          if (data.user_reaction === 'DISLIKE') {
            dislikeBtn.classList.add('active');
          } else {
            dislikeBtn.classList.remove('active');
          }
        }
      }
    } catch (err) {
      console.error('Error en reacción de comentario:', err);
    }
  });

  // ── Toggle de sección de comentarios al pulsar icono de comentarios ──
  document.addEventListener('click', (e) => {
    const toggleBtn = e.target.closest('.action-toggle-comments');
    if (!toggleBtn) return;
    e.preventDefault();
    const postId = toggleBtn.dataset.postId;
    const commentsSec = document.getElementById(`comments-section-${postId}`);
    if (commentsSec) {
      const isCollapsed = commentsSec.classList.toggle('collapsed');
      if (!isCollapsed) {
        const input = commentsSec.querySelector('.new-comment-input');
        if (input) input.focus();
      }
    }
  });

  // ── 3. Barra Dinámica para Responder Comentarios (Inline con misma estética) ──
  document.addEventListener('click', (e) => {
    // Click en botón "Responder" de cualquier comentario
    const trigger = e.target.closest('.comment-reply-trigger');
    if (trigger) {
      e.preventDefault();
      const commentId = trigger.dataset.commentId;
      const author = trigger.dataset.author || 'usuario';
      const commentCard = trigger.closest('.comment-card');
      const postCard = trigger.closest('.post-card');
      const postId = postCard ? postCard.dataset.postId : '';

      if (!commentCard || !postId || !commentId) return;

      // Si ya está abierta en este mismo comentario, hacer toggle para cerrarla
      const existingInThisCard = document.getElementById(`inline-reply-box-${commentId}`);
      if (existingInThisCard) {
        existingInThisCard.remove();
        return;
      }

      // Cerrar cualquier otra caja de respuesta abierta
      closeAllInlineReplyBoxes();

      const actionsBar = commentCard.querySelector('.comment-actions-bar');
      if (!actionsBar) return;

      const replyHtml = `
        <div class="inline-reply-container" id="inline-reply-box-${commentId}" data-post-id="${postId}" data-comment-id="${commentId}">
          <div class="replying-to-banner">
            <div class="replying-to-info">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2">
                <polyline points="9 17 4 12 9 7" />
                <path d="M20 18v-2a4 4 0 0 0-4-4H4" />
              </svg>
              <span>Respondiendo a <strong class="replying-target-name">@${author}</strong></span>
            </div>
            <button type="button" class="cancel-replying-btn" title="Cancelar respuesta">
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
              <span>Cancelar</span>
            </button>
          </div>

          <div class="new-comment-bar reply-comment-bar">
            <input type="text" 
                   class="new-comment-input inline-reply-input" 
                   placeholder="Responder a ${author}..." 
                   autocomplete="off">
            <label class="comment-attach-btn" title="Adjuntar imagen (PNG o JPG)">
              <input type="file" name="imagen" class="comment-image-input" accept="image/png,image/jpeg,.png,.jpg,.jpeg" hidden>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                <circle cx="8.5" cy="8.5" r="1.5" />
                <polyline points="21 15 16 10 5 21" />
              </svg>
            </label>
            <button type="button" class="new-comment-btn inline-reply-submit-btn" title="Publicar respuesta" aria-label="Responder">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
              <span class="new-comment-btn-text">Responder</span>
            </button>
          </div>
          <div class="comment-image-preview d-none">
            <img src="" alt="Vista previa" class="comment-preview-thumb">
            <span class="comment-preview-name"></span>
            <button type="button" class="comment-preview-remove" title="Quitar imagen">&times;</button>
          </div>
        </div>
      `;

      actionsBar.insertAdjacentHTML('afterend', replyHtml);

      const newContainer = document.getElementById(`inline-reply-box-${commentId}`);
      if (newContainer) {
        const input = newContainer.querySelector('.inline-reply-input');
        if (input) {
          input.focus();
          input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }
      return;
    }

    // Cancelar respuesta inline
    const cancelReplyBtn = e.target.closest('.cancel-replying-btn');
    if (cancelReplyBtn) {
      e.preventDefault();
      const container = cancelReplyBtn.closest('.inline-reply-container');
      if (container) container.remove();
      return;
    }

    // Enviar respuesta desde el botón dentro de la barra inline
    const replySubmitBtn = e.target.closest('.inline-reply-submit-btn');
    if (replySubmitBtn) {
      e.preventDefault();
      const container = replySubmitBtn.closest('.inline-reply-container');
      if (container) handleSendInlineReply(container);
      return;
    }
  });

  // ── Previsualización y limpieza de imagen adjunta en comentarios y respuestas ──
  function clearCommentImageSelection(scopeEl) {
    if (!scopeEl) return;
    const fileInput = scopeEl.querySelector('.comment-image-input');
    const preview = scopeEl.querySelector('.comment-image-preview');
    const thumb = scopeEl.querySelector('.comment-preview-thumb');
    const nameEl = scopeEl.querySelector('.comment-preview-name');
    const attachBtn = scopeEl.querySelector('.comment-attach-btn');
    if (fileInput) fileInput.value = '';
    if (thumb) thumb.src = '';
    if (nameEl) nameEl.textContent = '';
    if (preview) preview.classList.add('d-none');
    if (attachBtn) attachBtn.classList.remove('has-file');
  }

  document.addEventListener('change', (e) => {
    const fileInput = e.target.closest('.comment-image-input');
    if (!fileInput) return;
    const scopeEl = fileInput.closest('.new-comment-form, .inline-reply-container');
    if (!scopeEl) return;

    const file = fileInput.files && fileInput.files[0];
    if (!file) {
      clearCommentImageSelection(scopeEl);
      return;
    }

    const nombre = (file.name || '').toLowerCase();
    const extOk = /\.(png|jpe?g)$/.test(nombre);
    const mimeOk = ['image/png', 'image/jpeg'].includes(file.type);
    if (!extOk || !mimeOk) {
      showToast('Formato no permitido. Solo se aceptan imágenes PNG o JPG.', true);
      clearCommentImageSelection(scopeEl);
      return;
    }

    if (file.size > 8 * 1024 * 1024) {
      showToast('La imagen supera el tamaño máximo permitido (8 MB).', true);
      clearCommentImageSelection(scopeEl);
      return;
    }

    const preview = scopeEl.querySelector('.comment-image-preview');
    const thumb = scopeEl.querySelector('.comment-preview-thumb');
    const nameEl = scopeEl.querySelector('.comment-preview-name');
    const attachBtn = scopeEl.querySelector('.comment-attach-btn');

    if (nameEl) nameEl.textContent = file.name;
    if (preview) preview.classList.remove('d-none');
    if (attachBtn) attachBtn.classList.add('has-file');

    if (thumb) {
      const reader = new FileReader();
      reader.onload = (ev) => {
        thumb.src = ev.target.result;
      };
      reader.readAsDataURL(file);
    }
  });

  document.addEventListener('click', (e) => {
    const removeBtn = e.target.closest('.comment-preview-remove');
    if (!removeBtn) return;
    e.preventDefault();
    const scopeEl = removeBtn.closest('.new-comment-form, .inline-reply-container');
    clearCommentImageSelection(scopeEl);
  });

  // Cerrar todas las barras de respuesta inline
  function closeAllInlineReplyBoxes() {
    document.querySelectorAll('.inline-reply-container').forEach(el => el.remove());
  }

  // Enviar respuesta con tecla Enter o cancelar con Escape
  document.addEventListener('keydown', (e) => {
    const replyInput = e.target.closest('.inline-reply-input');
    if (replyInput) {
      const container = replyInput.closest('.inline-reply-container');
      if (e.key === 'Enter') {
        e.preventDefault();
        if (container) handleSendInlineReply(container);
      } else if (e.key === 'Escape') {
        if (container) container.remove();
      }
    }
  });

  // Helper para procesar envío de respuesta inline
  async function handleSendInlineReply(container) {
    if (!container) return;
    const postId = container.dataset.postId;
    const padreId = container.dataset.commentId;
    const input = container.querySelector('.inline-reply-input');
    const fileInput = container.querySelector('.comment-image-input');
    const submitBtn = container.querySelector('.inline-reply-submit-btn');
    const texto = input ? input.value.trim() : '';
    const imagenFile = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;

    if (!postId || !padreId || (!texto && !imagenFile)) return;
    if (submitBtn) submitBtn.disabled = true;

    try {
      const formData = new FormData();
      formData.append('texto', texto);
      formData.append('padre_id', padreId);
      if (imagenFile) {
        formData.append('imagen', imagenFile);
      }

      const res = await fetch(`/feed/comentar/${postId}/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== 'ok') {
        showToast(data.message || 'Error al publicar respuesta', true);
        return;
      }

      container.remove();

      const repliesThread = document.getElementById(`replies-for-${padreId}`);
      if (repliesThread) {
        const rep = data.comentario;
        const newReplyHtml = createReplyHtml(rep, postId);
        repliesThread.insertAdjacentHTML('beforeend', newReplyHtml);
      }

      updatePostCommentCount(postId, data.total_comentarios);
      showToast('Respuesta publicada');
    } catch (err) {
      console.error('Error al responder comentario:', err);
      showToast('Error al publicar respuesta', true);
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  // ── 4. Enviar Nuevo Comentario Principal (Barra Superior) ──
  document.addEventListener('submit', async (e) => {
    const form = e.target.closest('.new-comment-form');
    if (!form) return;

    e.preventDefault();
    const postId = form.dataset.postId;
    const input = form.querySelector('.new-comment-input');
    const fileInput = form.querySelector('.comment-image-input');
    const texto = input ? input.value.trim() : '';
    const imagenFile = fileInput && fileInput.files && fileInput.files[0] ? fileInput.files[0] : null;
    if (!postId || (!texto && !imagenFile)) return;

    const btn = form.querySelector('.new-comment-btn');
    if (btn) btn.disabled = true;

    try {
      const formData = new FormData();
      formData.append('texto', texto);
      if (imagenFile) {
        formData.append('imagen', imagenFile);
      }

      const res = await fetch(`/feed/comentar/${postId}/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.status !== 'ok') {
        showToast(data.message || 'No se pudo enviar el comentario', true);
        return;
      }

      if (input) input.value = '';
      clearCommentImageSelection(form);

      const list = document.getElementById(`comments-list-${postId}`);
      if (list) {
        const c = data.comentario;
        const newCommentHtml = createCommentHtml(c, postId);
        list.insertAdjacentHTML('beforeend', newCommentHtml);
      }

      updatePostCommentCount(postId, data.total_comentarios);
      showToast('Comentario agregado');
    } catch (err) {
      console.error('Error al agregar comentario:', err);
      showToast('No se pudo enviar el comentario', true);
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  // ── Helper para actualizar contador de comentarios ──
  function updatePostCommentCount(postId, total) {
    const postCard = document.getElementById(`post-card-${postId}`);
    if (postCard) {
      const countEl = postCard.querySelector('.comment-count-display');
      if (countEl) countEl.textContent = total;
    }
  }

  // ── 6. Menú de 3 Puntos (Dropdown de Opciones de Publicación) ──
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.post-menu-trigger-btn, .admin-mod-trigger-btn');
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      const postId = trigger.dataset.postId;
      const dropdown = document.getElementById(`post-menu-dropdown-${postId}`) ||
                       document.getElementById(`admin-mod-dropdown-${postId}`);
      // Cerrar otros dropdowns abiertos
      document.querySelectorAll('.post-menu-dropdown.show, .admin-mod-dropdown.show').forEach(d => {
        if (d !== dropdown) d.classList.remove('show');
      });
      if (dropdown) dropdown.classList.toggle('show');
      return;
    }

    // Cerrar dropdown si se hace click fuera
    if (!e.target.closest('.post-menu-dropdown, .admin-mod-dropdown')) {
      document.querySelectorAll('.post-menu-dropdown.show, .admin-mod-dropdown.show').forEach(d => d.classList.remove('show'));
    }
  });

  // ── 6.1. Modal de Edición de Publicación (Autor o Admin) ──
  const editPostModal = document.getElementById('editPostModal');
  const editPostForm = document.getElementById('editPostForm');
  const editPostId = document.getElementById('editPostId');
  const editPostTitulo = document.getElementById('editPostTitulo');
  const editPostCategoria = document.getElementById('editPostCategoria');
  const editPostContenido = document.getElementById('editPostContenido');
  const closeEditPostModalBtn = document.getElementById('closeEditPostModalBtn');
  const cancelEditPostBtn = document.getElementById('cancelEditPostBtn');

  function openEditPostModal(postId, titulo, categoria, contenido) {
    if (!editPostModal) return;
    editPostId.value = postId;
    if (editPostTitulo) editPostTitulo.value = titulo || '';
    if (editPostCategoria) editPostCategoria.value = categoria || 'VIAS';
    if (editPostContenido) editPostContenido.value = contenido || '';
    editPostModal.classList.add('active');
  }

  function closeEditPostModal() {
    if (editPostModal) editPostModal.classList.remove('active');
  }

  if (closeEditPostModalBtn) closeEditPostModalBtn.addEventListener('click', closeEditPostModal);
  if (cancelEditPostBtn) cancelEditPostBtn.addEventListener('click', closeEditPostModal);

  // Click en "Editar publicación"
  document.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.btn-action-edit-post');
    if (!editBtn) return;
    e.preventDefault();
    const postId = editBtn.dataset.postId;
    const titulo = editBtn.dataset.titulo || '';
    const categoria = editBtn.dataset.categoria || 'VIAS';
    const contenido = editBtn.dataset.contenido || '';

    // Cerrar dropdown
    const dropdown = document.getElementById(`post-menu-dropdown-${postId}`);
    if (dropdown) dropdown.classList.remove('show');

    openEditPostModal(postId, titulo, categoria, contenido);
  });

  // Enviar edición de publicación
  if (editPostForm) {
    editPostForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const postId = editPostId.value;
      const titulo = editPostTitulo ? editPostTitulo.value.trim() : '';
      const categoria = editPostCategoria ? editPostCategoria.value : 'VIAS';
      const contenido = editPostContenido ? editPostContenido.value.trim() : '';
      if (!postId) return;

      const saveBtn = document.getElementById('saveEditPostBtn');
      if (saveBtn) saveBtn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('titulo', titulo);
        formData.append('categoria', categoria);
        formData.append('contenido', contenido);

        const res = await fetch(`/feed/publicacion/${postId}/editar/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });

        const data = await res.json();
        if (data.status === 'ok') {
          closeEditPostModal();

          const pub = data.publicacion;
          // Actualizar texto con renderizado de menciones
          const contentText = document.getElementById(`post-content-text-${postId}`);
          if (contentText) contentText.innerHTML = renderMentionsHtml(escapeHtml(pub.contenido));

          // Actualizar título y categoría
          const titleRow = document.getElementById(`post-title-row-${postId}`);
          const titleText = document.getElementById(`post-title-${postId}`);
          const catBadge = document.getElementById(`post-category-${postId}`);

          if (pub.titulo) {
            if (titleText) titleText.textContent = pub.titulo;
            if (titleRow) titleRow.style.display = 'flex';
          } else {
            if (titleRow) titleRow.style.display = 'none';
          }

          if (catBadge) catBadge.textContent = pub.categoria_display;

          // Actualizar dataset en el botón editar
          const editBtn = document.querySelector(`.btn-action-edit-post[data-post-id="${postId}"]`);
          if (editBtn) {
            editBtn.dataset.titulo = pub.titulo;
            editBtn.dataset.categoria = pub.categoria;
            editBtn.dataset.contenido = pub.contenido;
          }

          showToast('¡Publicación actualizada con éxito!');
        } else {
          showToast(data.message || 'Error al actualizar', true);
        }
      } catch (err) {
        console.error('Error al editar publicación:', err);
        showToast('Error de conexión', true);
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });
  }

  // ── 6.2. Modal de Edición de Comentarios (Autor o Administrador) ──
  const editCommentModal = document.getElementById('editCommentModal');
  const editCommentForm = document.getElementById('editCommentForm');
  const editCommentId = document.getElementById('editCommentId');
  const editCommentTexto = document.getElementById('editCommentTexto');
  const closeEditCommentModalBtn = document.getElementById('closeEditCommentModalBtn');
  const cancelEditCommentBtn = document.getElementById('cancelEditCommentBtn');

  function openEditCommentModal(commentId, currentText) {
    if (!editCommentModal) return;
    if (editCommentId) editCommentId.value = commentId;
    if (editCommentTexto) {
      editCommentTexto.value = currentText;
      setTimeout(() => editCommentTexto.focus(), 60);
    }
    editCommentModal.classList.add('active');
  }

  function closeEditCommentModal() {
    if (editCommentModal) editCommentModal.classList.remove('active');
  }

  if (closeEditCommentModalBtn) closeEditCommentModalBtn.addEventListener('click', closeEditCommentModal);
  if (cancelEditCommentBtn) cancelEditCommentBtn.addEventListener('click', closeEditCommentModal);

  // Gatillar abrir modal editar comentario
  document.addEventListener('click', (e) => {
    const editBtn = e.target.closest('.btn-action-edit-comment');
    if (!editBtn) return;
    e.preventDefault();
    const commentId = editBtn.dataset.commentId;
    const textEl = document.getElementById(`comment-text-${commentId}`);
    const currentText = textEl ? textEl.textContent.trim() : '';
    openEditCommentModal(commentId, currentText);
  });

  // Guardar edición de comentario
  if (editCommentForm) {
    editCommentForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const commentId = editCommentId.value;
      const texto = editCommentTexto.value.trim();
      if (!commentId || !texto) return;

      const saveBtn = document.getElementById('saveEditCommentBtn');
      if (saveBtn) saveBtn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('texto', texto);

        const res = await fetch(`/feed/comentario/${commentId}/editar/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });

        if (!res.ok) throw new Error('Error al editar comentario');
        const data = await res.json();

        if (data.status === 'ok') {
          closeEditCommentModal();
          const textEl = document.getElementById(`comment-text-${commentId}`);
          if (textEl) {
            textEl.innerHTML = renderMentionsHtml(escapeHtml(data.comentario.texto));
          }
          showToast('¡Comentario editado con éxito!');
        } else {
          showToast(data.message || 'Error al editar', true);
        }
      } catch (err) {
        console.error('Error al editar comentario:', err);
        showToast('Error de conexión al editar comentario', true);
      } finally {
        if (saveBtn) saveBtn.disabled = false;
      }
    });
  }

  // Copiar enlace permanente
  document.addEventListener('click', (e) => {
    const copyBtn = e.target.closest('.btn-action-copy-link');
    if (!copyBtn) return;
    e.preventDefault();
    const postId = copyBtn.dataset.postId;
    const dropdown = document.getElementById(`post-menu-dropdown-${postId}`);
    if (dropdown) dropdown.classList.remove('show');

    // Enlace directo a la vista de detalle de la publicación
    const enlace = window.location.origin + `/feed/publicacion/${postId}/`;
    copiarAlPortapapeles(enlace);
  });

  // Copia texto al portapapeles con fallback para contextos no seguros (HTTP/IP local).
  // La API navigator.clipboard solo existe en https o localhost; si no, usamos execCommand.
  function copiarAlPortapapeles(texto) {
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(texto)
        .then(() => showToast('¡Enlace de publicación copiado!'))
        .catch(() => copiarFallback(texto));
    } else {
      copiarFallback(texto);
    }
  }

  function copiarFallback(texto) {
    try {
      const ta = document.createElement('textarea');
      ta.value = texto;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.top = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      showToast(ok ? '¡Enlace de publicación copiado!' : 'No se pudo copiar. Copia manualmente: ' + texto, !ok);
    } catch (err) {
      showToast('No se pudo copiar. Copia manualmente: ' + texto, true);
    }
  }

  // ── 7. Moderación de Publicación: Censurar / Descensurar ──
  document.addEventListener('click', async (e) => {
    const censorBtn = e.target.closest('.btn-action-censor-post');
    if (!censorBtn) return;

    e.preventDefault();
    const postId = censorBtn.dataset.postId;
    if (!postId) return;

    try {
      const formData = new FormData();
      formData.append('accion', 'CENSURAR');

      const res = await fetch(`/feed/publicacion/${postId}/moderar/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      const data = await res.json();
      if (data.status === 'ok') {
        const banner = document.getElementById(`censored-banner-${postId}`);
        const contentWrap = document.getElementById(`post-content-wrap-${postId}`);
        const postCard = document.getElementById(`post-card-${postId}`);
        const label = censorBtn.querySelector('.censor-btn-text');
        const mediaContainer = contentWrap ? contentWrap.querySelector('.post-media-container') : null;

        if (data.censurado) {
          if (banner) banner.classList.remove('d-none');
          if (contentWrap) contentWrap.classList.add('is-censored');
          if (postCard) {
            postCard.dataset.censurado = 'true';
            postCard.classList.add('is-censored-card');
          }
          if (mediaContainer) {
            mediaContainer.classList.remove('is-expandable-media');
            mediaContainer.classList.add('is-censored-media');
            mediaContainer.removeAttribute('role');
            mediaContainer.removeAttribute('tabindex');
            mediaContainer.removeAttribute('title');
            if (!mediaContainer.querySelector('.censor-media-shield')) {
              const shield = document.createElement('div');
              shield.className = 'censor-media-shield';
              shield.innerHTML = `
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                <div class="censor-media-shield-text">
                  <strong>Imagen censurada por moderación</strong>
                  <span>Contenido restringido por incumplimiento de normas</span>
                </div>
              `;
              mediaContainer.appendChild(shield);
            }
          }
          if (label) label.textContent = 'Descensurar';
        } else {
          if (banner) banner.classList.add('d-none');
          if (contentWrap) contentWrap.classList.remove('is-censored');
          if (postCard) {
            postCard.dataset.censurado = 'false';
            postCard.classList.remove('is-censored-card');
          }
          if (mediaContainer) {
            mediaContainer.classList.remove('is-censored-media');
            const shield = mediaContainer.querySelector('.censor-media-shield');
            if (shield) shield.remove();
            if (document.querySelector('.portal-main-detalle')) {
              mediaContainer.classList.add('is-expandable-media');
              mediaContainer.setAttribute('role', 'button');
              mediaContainer.setAttribute('tabindex', '0');
              mediaContainer.setAttribute('title', 'Haz clic para ampliar la imagen');
            }
          }
          if (label) label.textContent = 'Censurar';
        }

        // Cerrar menú dropdown
        const dropdown = document.getElementById(`post-menu-dropdown-${postId}`) || document.getElementById(`admin-mod-dropdown-${postId}`);
        if (dropdown) dropdown.classList.remove('show');

        showToast(data.message);
      } else {
        showToast(data.message || 'Error al moderar publicación', true);
      }
    } catch (err) {
      console.error('Error al censurar publicación:', err);
      showToast('Error de conexión', true);
    }
  });

  // ── 8. Moderación de Comentarios: Censurar / Descensurar ──
  document.addEventListener('click', async (e) => {
    const censorBtn = e.target.closest('.btn-action-censor-comment');
    if (!censorBtn) return;

    e.preventDefault();
    const commentId = censorBtn.dataset.commentId;
    if (!commentId) return;

    try {
      const formData = new FormData();
      formData.append('accion', 'CENSURAR');

      const res = await fetch(`/feed/comentario/${commentId}/moderar/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      const data = await res.json();
      if (data.status === 'ok') {
        const textEl = document.getElementById(`comment-text-${commentId}`);
        const mediaEl = document.getElementById(`comment-media-${commentId}`);
        const label = censorBtn.querySelector('.com-censor-btn-text');

        if (data.censurado) {
          if (textEl) {
            if (textEl.dataset.originalText === undefined) {
              textEl.dataset.originalText = textEl.textContent.trim();
            }
            textEl.innerHTML = '<span class="censored-comment-badge">⚠️ <em>Comentario censurado por moderación.</em></span>';
            textEl.classList.remove('d-none');
            textEl.classList.add('is-censored-text');
          }
          if (mediaEl) {
            mediaEl.classList.remove('is-expandable-media');
            mediaEl.classList.add('is-censored-media');
            mediaEl.removeAttribute('role');
            mediaEl.removeAttribute('tabindex');
            mediaEl.removeAttribute('title');
            if (!mediaEl.querySelector('.censor-media-shield')) {
              const shield = document.createElement('div');
              shield.className = 'censor-media-shield censor-comment-shield';
              shield.innerHTML = `
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                  <line x1="12" y1="9" x2="12" y2="13" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
                <div class="censor-media-shield-text">
                  <strong>Imagen censurada</strong>
                </div>
              `;
              mediaEl.appendChild(shield);
            }
          }
          if (label) label.textContent = 'Descensurar';
        } else {
          if (textEl) {
            const original = textEl.dataset.originalText !== undefined ? textEl.dataset.originalText : '';
            textEl.textContent = original;
            textEl.classList.remove('is-censored-text');
            if (!original && mediaEl) {
              textEl.classList.add('d-none');
            }
          }
          if (mediaEl) {
            mediaEl.classList.remove('is-censored-media');
            mediaEl.classList.add('is-expandable-media');
            mediaEl.setAttribute('role', 'button');
            mediaEl.setAttribute('tabindex', '0');
            mediaEl.setAttribute('title', 'Haz clic para ampliar la imagen');
            const shield = mediaEl.querySelector('.censor-media-shield');
            if (shield) shield.remove();
          }
          if (label) label.textContent = 'Censurar';
        }

        showToast(data.message);
      } else {
        showToast(data.message || 'Error al moderar comentario', true);
      }
    } catch (err) {
      console.error('Error al censurar comentario:', err);
      showToast('Error de conexión', true);
    }
  });

  // ── 9. Modal de Eliminación (Publicación / Comentario) ──
  const deleteModal = document.getElementById('deleteConfirmModal');
  const deleteTargetType = document.getElementById('deleteTargetType');
  const deleteTargetId = document.getElementById('deleteTargetId');
  const deletePostRefId = document.getElementById('deletePostRefId');
  const deleteTargetPreview = document.getElementById('deleteTargetPreview');
  const confirmDeleteBtn = document.getElementById('confirmDeleteBtn');
  const closeDeleteModalBtn = document.getElementById('closeDeleteModalBtn');
  const cancelDeleteBtn = document.getElementById('cancelDeleteBtn');

  function openDeleteModal(tipo, id, label, postRefId = '') {
    if (!deleteModal) return;
    deleteTargetType.value = tipo;
    deleteTargetId.value = id;
    if (deletePostRefId) deletePostRefId.value = postRefId;
    if (deleteTargetPreview) deleteTargetPreview.textContent = `${tipo === 'publicacion' ? 'Publicación' : 'Comentario'} de: ${label}`;
    deleteModal.classList.add('active');
  }

  function closeDeleteModal() {
    if (deleteModal) deleteModal.classList.remove('active');
  }

  if (closeDeleteModalBtn) closeDeleteModalBtn.addEventListener('click', closeDeleteModal);
  if (cancelDeleteBtn) cancelDeleteBtn.addEventListener('click', closeDeleteModal);

  // Gatillar eliminar publicación
  document.addEventListener('click', (e) => {
    const delBtn = e.target.closest('.btn-action-delete-post');
    if (!delBtn) return;
    e.preventDefault();
    const postId = delBtn.dataset.postId;
    const author = delBtn.dataset.author || 'Usuario';
    openDeleteModal('publicacion', postId, author);
  });

  // Gatillar eliminar comentario
  document.addEventListener('click', (e) => {
    const delBtn = e.target.closest('.btn-action-delete-comment');
    if (!delBtn) return;
    e.preventDefault();
    const commentId = delBtn.dataset.commentId;
    const postId = delBtn.dataset.postId || '';
    const author = delBtn.dataset.author || 'Usuario';
    openDeleteModal('comentario', commentId, author, postId);
  });

  // Ejecutar eliminación confirmada
  if (confirmDeleteBtn) {
    confirmDeleteBtn.addEventListener('click', async () => {
      const tipo = deleteTargetType.value;
      const id = deleteTargetId.value;
      const postRef = deletePostRefId ? deletePostRefId.value : '';
      if (!tipo || !id) return;

      confirmDeleteBtn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('accion', 'ELIMINAR');

        const url = tipo === 'publicacion' ? `/feed/publicacion/${id}/eliminar/` : `/feed/comentario/${id}/eliminar/`;
        const res = await fetch(url, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });

        const data = await res.json();
        if (data.status === 'ok') {
          closeDeleteModal();

          if (tipo === 'publicacion') {
            const card = document.getElementById(`post-card-${id}`);
            if (card) {
              card.style.transition = 'all 0.3s ease';
              card.style.opacity = '0';
              card.style.transform = 'translateY(-12px)';
              setTimeout(() => card.remove(), 300);
            }
            // Retirar de "Actividad Reciente" la actividad de la publicación eliminada
            removeActivityByPubId(id);
            if (Array.isArray(data.actividades)) {
              renderActivityList(data.actividades);
            } else {
              refreshActivityFromServer();
            }
          } else {
            const commentCard = document.getElementById(`comment-card-${id}`);
            if (commentCard) {
              commentCard.style.transition = 'all 0.3s ease';
              commentCard.style.opacity = '0';
              commentCard.style.transform = 'translateX(-12px)';
              setTimeout(() => commentCard.remove(), 300);
            }
            if (postRef && data.total_comentarios !== undefined) {
              updatePostCommentCount(postRef, data.total_comentarios);
            }
          }

          showToast(data.message);
        } else {
          showToast(data.message || 'Error al eliminar', true);
        }
      } catch (err) {
        console.error('Error al ejecutar eliminación:', err);
        showToast('Error de conexión', true);
      } finally {
        confirmDeleteBtn.disabled = false;
      }
    });
  }

  // ── 10. Modal de Reportar Contenido (Ciudadanos) ──
  const reportModal = document.getElementById('reportContentModal');
  const reportForm = document.getElementById('reportContentForm');
  const reportTargetType = document.getElementById('reportTargetType');
  const reportTargetId = document.getElementById('reportTargetId');
  const reportTargetTypeName = document.getElementById('reportTargetTypeName');
  const reportTargetAuthor = document.getElementById('reportTargetAuthor');
  const closeReportModalBtn = document.getElementById('closeReportModalBtn');
  const cancelReportBtn = document.getElementById('cancelReportBtn');

  function openReportModal(tipo, id, author) {
    if (!reportModal) return;
    reportTargetType.value = tipo;
    reportTargetId.value = id;
    if (reportTargetTypeName) reportTargetTypeName.textContent = tipo === 'publicacion' ? 'publicación' : 'comentario';
    if (reportTargetAuthor) reportTargetAuthor.textContent = author;
    reportModal.classList.add('active');
  }

  function closeReportModal() {
    if (reportModal) reportModal.classList.remove('active');
    if (reportForm) reportForm.reset();
  }

  if (closeReportModalBtn) closeReportModalBtn.addEventListener('click', closeReportModal);
  if (cancelReportBtn) cancelReportBtn.addEventListener('click', closeReportModal);

  // Click en reportar publicación
  document.addEventListener('click', (e) => {
    const reportBtn = e.target.closest('.action-report-post-btn');
    if (!reportBtn) return;
    e.preventDefault();
    const postId = reportBtn.dataset.postId;
    const author = reportBtn.dataset.author || 'Usuario';
    openReportModal('publicacion', postId, author);
  });

  // Click en reportar comentario
  document.addEventListener('click', (e) => {
    const reportBtn = e.target.closest('.btn-action-report-comment');
    if (!reportBtn) return;
    e.preventDefault();
    const commentId = reportBtn.dataset.commentId;
    const author = reportBtn.dataset.author || 'Usuario';
    openReportModal('comentario', commentId, author);
  });

  // Enviar reporte
  if (reportForm) {
    reportForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const tipo = reportTargetType.value;
      const id = reportTargetId.value;
      const motivoEl = reportForm.querySelector('input[name="reportMotivo"]:checked');
      const motivo = motivoEl ? motivoEl.value : 'INAPROPIADO';
      const descEl = document.getElementById('reportDescripcion');
      const descripcion = descEl ? descEl.value.trim() : '';

      if (!tipo || !id) return;

      const submitBtn = document.getElementById('submitReportBtn');
      if (submitBtn) submitBtn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('motivo', motivo);
        formData.append('descripcion', descripcion);

        const url = tipo === 'publicacion' ? `/feed/publicacion/${id}/reportar/` : `/feed/comentario/${id}/reportar/`;
        const res = await fetch(url, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });

        const data = await res.json();
        closeReportModal();
        showToast(data.message, data.status === 'error');
      } catch (err) {
        console.error('Error al enviar reporte:', err);
        showToast('Error de conexión al enviar reporte', true);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  function renderMentionsHtml(escapedText) {
    if (!escapedText) return '';
    return escapedText.replace(
      /(?<![\w@])@([A-Za-z0-9_]+(?:[.\-][A-Za-z0-9_]+)*)/g,
      '<a href="/perfil/$1/" class="user-mention" onclick="event.stopPropagation();" title="Ver perfil de @$1">@$1</a>'
    );
  }

  // ── Generador de HTML para comentario nuevo ──
  function createCommentHtml(c, postId) {
    const safeInitials = escapeHtml(c.initials || 'UR');
    const safeAuthor = escapeHtml(c.autor_nombre);
    const safeTime = escapeHtml(c.tiempo);
    const safeText = renderMentionsHtml(escapeHtml(c.texto));
    const textClass = safeText ? 'comment-body-text' : 'comment-body-text d-none';
    const avatarHtml = c.avatar_url
      ? `<img src="${escapeHtml(c.avatar_url)}" alt="${safeAuthor}" class="comment-avatar-circle comment-avatar-img" loading="lazy" decoding="async">`
      : `<div class="comment-avatar-circle">${safeInitials}</div>`;
    const mediaHtml = c.imagen_url
      ? `<div class="comment-media-container is-expandable-media" id="comment-media-${c.id}" title="Haz clic para ampliar la imagen" role="button" tabindex="0">
           <img src="${escapeHtml(c.imagen_url)}" alt="Imagen de comentario" class="comment-media-img post-media-img" loading="lazy" decoding="async">
         </div>`
      : '';
    return `
      <div class="comment-card" id="comment-card-${c.id}" style="animation: fadeInDown 0.22s ease;">
        <div class="comment-header">
          <div class="comment-author-wrap">
            <a class="comment-author-link" href="/perfil/" title="Ver mi perfil">
              ${avatarHtml}
              <span class="comment-author-name">${safeAuthor}</span>
            </a>
          </div>
          <span class="comment-timestamp">${safeTime}</span>
        </div>
        <p class="${textClass}" id="comment-text-${c.id}">${safeText}</p>
        ${mediaHtml}
        <div class="comment-actions-bar">
          <button type="button" class="comment-act-btn comment-like-btn" data-comment-id="${c.id}" data-type="LIKE" title="Me gusta">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
            </svg>
            <span class="com-like-count">0</span>
          </button>
          <button type="button" class="comment-act-btn comment-dislike-btn" data-comment-id="${c.id}" data-type="DISLIKE" title="No me gusta">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
            </svg>
            <span class="com-dislike-count">0</span>
          </button>
          <button type="button" class="comment-act-btn comment-reply-trigger" data-comment-id="${c.id}" data-author="${safeAuthor}">
            Responder
          </button>

          <!-- Menú de 3 puntos del comentario recién creado (autor: editar/eliminar) -->
          <div class="comment-menu-wrapper">
            <button type="button" class="comment-act-btn comment-menu-trigger" data-comment-id="${c.id}" title="Más opciones">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/>
              </svg>
            </button>
            <div class="comment-menu-dropdown" id="comment-menu-dropdown-${c.id}">
              <button type="button" class="comment-menu-item btn-action-edit-comment" data-comment-id="${c.id}" data-post-id="${postId}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                <span>Editar</span>
              </button>
              <button type="button" class="comment-menu-item text-danger btn-action-delete-comment" data-comment-id="${c.id}" data-post-id="${postId}" data-author="${safeAuthor}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
                <span>Eliminar</span>
              </button>
            </div>
          </div>
        </div>
        <div class="comment-replies-thread" id="replies-for-${c.id}"></div>
      </div>
    `;
  }

  // ── Generador de HTML para respuesta nueva ──
  function createReplyHtml(rep, postId = '') {
    const safeInitials = escapeHtml(rep.initials || 'UR');
    const safeAuthor = escapeHtml(rep.autor_nombre);
    const safeTime = escapeHtml(rep.tiempo);
    const safeText = renderMentionsHtml(escapeHtml(rep.texto));
    const textClass = safeText ? 'comment-body-text' : 'comment-body-text d-none';
    const avatarHtml = rep.avatar_url
      ? `<img src="${escapeHtml(rep.avatar_url)}" alt="${safeAuthor}" class="comment-avatar-circle comment-avatar-img" style="width:22px; height:22px;" loading="lazy" decoding="async">`
      : `<div class="comment-avatar-circle" style="width:22px; height:22px; font-size:0.68rem;">${safeInitials}</div>`;
    const mediaHtml = rep.imagen_url
      ? `<div class="comment-media-container is-expandable-media" id="comment-media-${rep.id}" title="Haz clic para ampliar la imagen" role="button" tabindex="0">
           <img src="${escapeHtml(rep.imagen_url)}" alt="Imagen de respuesta" class="comment-media-img post-media-img" loading="lazy" decoding="async">
         </div>`
      : '';
    return `
      <div class="reply-card" id="comment-card-${rep.id}" style="animation: fadeInDown 0.22s ease;">
        <div class="comment-header">
          <div class="comment-author-wrap">
            <a class="comment-author-link" href="/perfil/" title="Ver mi perfil">
              ${avatarHtml}
              <span class="comment-author-name" style="font-size:0.82rem;">${safeAuthor}</span>
            </a>
          </div>
          <span class="comment-timestamp">${safeTime}</span>
        </div>
        <p class="${textClass}" id="comment-text-${rep.id}" style="font-size:0.84rem;">${safeText}</p>
        ${mediaHtml}
        <div class="comment-actions-bar">
          <button type="button" class="comment-act-btn comment-like-btn" data-comment-id="${rep.id}" data-type="LIKE" title="Me gusta">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
            </svg>
            <span class="com-like-count">0</span>
          </button>
          <button type="button" class="comment-act-btn comment-dislike-btn" data-comment-id="${rep.id}" data-type="DISLIKE" title="No me gusta">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
            </svg>
            <span class="com-dislike-count">0</span>
          </button>

          <!-- Menú de 3 puntos de la respuesta recién creada (autor: editar/eliminar) -->
          <div class="comment-menu-wrapper">
            <button type="button" class="comment-act-btn comment-menu-trigger" data-comment-id="${rep.id}" title="Más opciones">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="1.5"/><circle cx="19" cy="12" r="1.5"/><circle cx="5" cy="12" r="1.5"/>
              </svg>
            </button>
            <div class="comment-menu-dropdown" id="comment-menu-dropdown-${rep.id}">
              <button type="button" class="comment-menu-item btn-action-edit-comment" data-comment-id="${rep.id}" data-post-id="${postId}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
                <span>Editar</span>
              </button>
              <button type="button" class="comment-menu-item text-danger btn-action-delete-comment" data-comment-id="${rep.id}" data-post-id="${postId}" data-author="${safeAuthor}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                </svg>
                <span>Eliminar</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  // ── Cierre de modales al pulsar fondo ──
  [reportModal, deleteModal, editPostModal, editCommentModal].forEach(modal => {
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.remove('active');
      });
    }
  });

  // =========================================================================
  // ── 8. Sistema Anti-Saturación en Segundo Plano para "Actividad Reciente" ──
  // ── (6 cupos fijos: 3 no resueltos + 3 resueltos con cola FIFO en vivo)   ──
  // =========================================================================
  const activityContainer = document.getElementById('activity-list-container');
  const feedStreamContainer = document.getElementById('feed-posts-stream');

  // Escapar texto y atributos para evitar inyección HTML/XSS
  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Construye el nodo DOM de un item de actividad a partir de un objeto {id, titulo, tiempo, tipo, publicacion_id}
  function buildActivityItem(act, entering = false) {
    const item = document.createElement('div');
    item.className = 'activity-item' + (entering ? ' activity-entering' : '');
    item.id = `activity-item-${act.id}`;
    item.dataset.actId = act.id;
    item.dataset.tipo = act.tipo;
    if (act.publicacion_id != null) item.dataset.pubId = act.publicacion_id;

    const dotColor = act.tipo === 'resuelta' ? 'green' : 'gray';
    item.innerHTML = `
      <div class="activity-dot ${dotColor}"></div>
      <div class="activity-info">
        <p class="activity-text">${escapeHtml(act.titulo)}</p>
        <span class="activity-time">${escapeHtml(act.tiempo || 'Hace un momento')}</span>
      </div>
    `;
    return item;
  }

  // Reemplaza por completo el contenido del widget con las 6 actividades del servidor
  // (3 no resueltas + 3 resueltas). Al derivarse de las publicaciones vivas, el tiempo
  // es real y las publicaciones eliminadas ya no aparecen.
  function renderActivityList(actividades) {
    if (!activityContainer || !Array.isArray(actividades)) return;
    activityContainer.innerHTML = '';
    if (actividades.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'activity-empty-state';
      empty.id = 'activity-empty-state';
      empty.innerHTML = '<p class="activity-text" style="color: var(--text-muted);">Aún no hay actividad reciente.</p>';
      activityContainer.appendChild(empty);
      return;
    }
    actividades.forEach(act => activityContainer.appendChild(buildActivityItem(act)));
  }

  // Retira del widget cualquier actividad asociada a una publicación eliminada
  function removeActivityByPubId(pubId) {
    if (!activityContainer || pubId == null) return;
    activityContainer
      .querySelectorAll(`.activity-item[data-pub-id="${pubId}"]`)
      .forEach(el => {
        el.classList.add('activity-leaving');
        setTimeout(() => el.remove(), 350);
      });
  }

  // Refresca el widget consultando al servidor (fuente de verdad basada en publicaciones)
  async function refreshActivityFromServer() {
    if (!activityContainer) return;
    try {
      const res = await fetch('/feed/api/actividades-recientes/', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'ok' && Array.isArray(data.actividades)) {
        renderActivityList(data.actividades);
      }
    } catch (_) {}
  }

  // ── Inserción de nueva publicación en el Feed (Muestra todas, sin límite) ──
  function insertPostIntoFeedStream(cardHtml) {
    if (!feedStreamContainer || !cardHtml) return;

    const temp = document.createElement('div');
    temp.innerHTML = cardHtml.trim();
    const newCard = temp.firstElementChild;
    if (!newCard) return;

    const postId = newCard.dataset.postId || (newCard.id ? newCard.id.replace('post-card-', '') : null);
    if (postId) {
      const existing = document.getElementById(`post-card-${postId}`);
      if (existing) existing.remove();
    }

    // Quitar mensaje vacío si existe
    const emptyState = feedStreamContainer.querySelector('.feed-empty-state');
    if (emptyState) emptyState.remove();

    newCard.classList.add('feed-card-entering');
    feedStreamContainer.prepend(newCard);
  }

  // ── Cambiar Estado de Incidencia (Marcar como Resuelta / Reabrir) ──
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-action-change-status');
    if (!btn) return;

    e.preventDefault();
    e.stopPropagation();
    const postId = btn.dataset.postId;
    const nuevoEstado = btn.dataset.estado || 'RESUELTA';
    if (!postId) return;

    // Cerrar dropdown
    document.querySelectorAll('.post-menu-dropdown.show').forEach(d => d.classList.remove('show'));

    try {
      const formData = new FormData();
      formData.append('estado', nuevoEstado);

      const res = await fetch(`/feed/publicacion/${postId}/cambiar-estado/`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': csrftoken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: formData,
      });

      if (!res.ok) throw new Error('Error al actualizar estado.');
      const data = await res.json();

      if (data.status === 'ok') {
        showToast(data.message || 'Estado actualizado correctamente');

        // Notificar por BroadcastChannel
        try {
          const chan = new BroadcastChannel('urbanreport_realtime_incidents');
          chan.postMessage({
            type: 'CAMBIO_ESTADO',
            id: data.id,
            estado: data.estado,
            es_resuelta: data.es_resuelta,
            actividad: data.actividad
          });
        } catch (_) {}

        // 1. Actualizar el diseño de la tarjeta en el feed comunitario
        const cardRes = await fetch(`/feed/api/post-card/${postId}/`);
        if (cardRes.ok) {
          const cardData = await cardRes.json();
          const existingCard = document.getElementById(`post-card-${postId}`);
          if (existingCard) {
            const temp = document.createElement('div');
            temp.innerHTML = cardData.html.trim();
            if (temp.firstElementChild) {
              existingCard.replaceWith(temp.firstElementChild);
            }
          }
        }

        // 2. Refrescar "Actividad Reciente" desde el servidor (fuente de verdad)
        refreshActivityFromServer();
      } else {
        showToast(data.message || 'No se pudo cambiar el estado', true);
      }
    } catch (err) {
      console.error('Error al cambiar estado de incidencia:', err);
      showToast('Error de conexión al cambiar estado', true);
    }
  });

  // ── Declinar Reporte de Incidencia con Motivo Predeterminado (Administrador) ──
  const declineReportModal = document.getElementById('declineReportModal');
  const declineReportForm = document.getElementById('declineReportForm');
  const declineReportPostId = document.getElementById('declineReportPostId');
  const declineReportTitle = document.getElementById('declineReportTitle');
  const declineReportAuthor = document.getElementById('declineReportAuthor');
  const declineReportDetalle = document.getElementById('declineReportDetalle');
  const closeDeclineReportModalBtn = document.getElementById('closeDeclineReportModalBtn');
  const cancelDeclineReportBtn = document.getElementById('cancelDeclineReportBtn');

  function closeDeclineReportModal() {
    if (declineReportModal) {
      declineReportModal.classList.remove('active');
    }
  }

  if (closeDeclineReportModalBtn) closeDeclineReportModalBtn.addEventListener('click', closeDeclineReportModal);
  if (cancelDeclineReportBtn) cancelDeclineReportBtn.addEventListener('click', closeDeclineReportModal);
  if (declineReportModal) {
    declineReportModal.addEventListener('click', (e) => {
      if (e.target === declineReportModal) closeDeclineReportModal();
    });
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.btn-action-decline-post');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();

    const postId = btn.dataset.postId;
    if (!postId || !declineReportModal) return;

    document.querySelectorAll('.post-menu-dropdown.show').forEach(d => d.classList.remove('show'));

    if (declineReportPostId) declineReportPostId.value = postId;
    if (declineReportTitle) declineReportTitle.textContent = `#REP-${postId}`;
    if (declineReportAuthor) declineReportAuthor.textContent = btn.dataset.author || 'Ciudadano';
    if (declineReportDetalle) declineReportDetalle.value = '';
    const defaultRadio = declineReportModal.querySelector('input[name="declineMotivo"][value="DUPLICADO"]');
    if (defaultRadio) defaultRadio.checked = true;

    declineReportModal.classList.add('active');
  });

  if (declineReportForm) {
    declineReportForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const postId = declineReportPostId ? declineReportPostId.value : '';
      if (!postId) return;

      const selectedRadio = declineReportForm.querySelector('input[name="declineMotivo"]:checked');
      const motivo = selectedRadio ? selectedRadio.value : 'NO_PROCEDE';
      const detalle = declineReportDetalle ? declineReportDetalle.value.trim() : '';

      const submitBtn = document.getElementById('confirmDeclineReportBtn');
      if (submitBtn) submitBtn.disabled = true;

      try {
        const formData = new FormData();
        formData.append('estado', 'DECLINADO');
        formData.append('motivo', motivo);
        if (detalle) formData.append('detalle', detalle);

        const res = await fetch(`/feed/publicacion/${postId}/cambiar-estado/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrftoken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: formData,
        });

        const data = await res.json();
        if (res.ok && data.status === 'ok') {
          closeDeclineReportModal();
          showToast(data.message || 'Reporte declinado y ciudadano notificado');

          try {
            const chan = new BroadcastChannel('urbanreport_realtime_incidents');
            chan.postMessage({
              type: 'CAMBIO_ESTADO',
              id: data.id,
              estado: data.estado,
              es_resuelta: data.es_resuelta,
              actividad: data.actividad,
            });
          } catch (_) {}

          const cardRes = await fetch(`/feed/api/post-card/${postId}/`);
          if (cardRes.ok) {
            const cardData = await cardRes.json();
            const existingCard = document.getElementById(`post-card-${postId}`);
            if (existingCard) {
              const temp = document.createElement('div');
              temp.innerHTML = cardData.html.trim();
              if (temp.firstElementChild) {
                existingCard.replaceWith(temp.firstElementChild);
              }
            }
          }
          refreshActivityFromServer();
        } else {
          showToast((data && data.message) || 'No se pudo declinar el reporte', true);
        }
      } catch (err) {
        console.error('Error al declinar reporte:', err);
        showToast('Error de conexión al declinar el reporte', true);
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  // ── Conexión en Tiempo Real via BroadcastChannel ──
  const feedRealtimeChannel = (typeof BroadcastChannel !== 'undefined') ?
    new BroadcastChannel('urbanreport_realtime_incidents') : null;

  if (feedRealtimeChannel) {
    feedRealtimeChannel.onmessage = async (e) => {
      const msg = e.data;
      if (!msg) return;

      if (msg.type === 'NUEVA_INCIDENCIA' && msg.incidente) {
        try {
          // 1. Agregar publicación al feed
          const res = await fetch(`/feed/api/post-card/${msg.incidente.id}/`);
          if (res.ok) {
            const data = await res.json();
            insertPostIntoFeedStream(data.html);
            showToast(`Nuevo reporte: ${msg.incidente.titulo || 'Incidencia urbana'}`);
          }
          // 2. Refrescar "Actividad Reciente" desde el servidor
          refreshActivityFromServer();
        } catch (err) {
          console.warn('Error al procesar nueva incidencia en tiempo real:', err);
        }
      } else if (msg.type === 'CAMBIO_ESTADO' && msg.id) {
        try {
          // Actualizar tarjeta en feed
          const res = await fetch(`/feed/api/post-card/${msg.id}/`);
          if (res.ok) {
            const data = await res.json();
            const existingCard = document.getElementById(`post-card-${msg.id}`);
            if (existingCard) {
              const temp = document.createElement('div');
              temp.innerHTML = data.html.trim();
              if (temp.firstElementChild) existingCard.replaceWith(temp.firstElementChild);
            }
          }
          // Refrescar "Actividad Reciente" desde el servidor
          refreshActivityFromServer();
        } catch (err) {
          console.warn('Error al sincronizar cambio de estado:', err);
        }
      }
    };
  }

  // Hook global invocado por modal_radicar.js en la misma ventana sin recargar
  window.handleRealtimePostAdded = async function (incidente) {
    if (!incidente || !incidente.id) return;
    try {
      // 1. Agregar al feed
      const res = await fetch(`/feed/api/post-card/${incidente.id}/`);
      if (res.ok) {
        const data = await res.json();
        insertPostIntoFeedStream(data.html);
      }
      // 2. Refrescar "Actividad Reciente" desde el servidor
      refreshActivityFromServer();
    } catch (err) {
      console.warn('Error al renderizar incidencia radicada localmente:', err);
    }
  };

  // ── Sincronización periódica de "Actividad Reciente" (cada 7s) ──
  // Reemplaza el widget con el estado real del servidor: refresca la hora relativa
  // (timesince) y retira publicaciones eliminadas. No corre si la pestaña está oculta.
  if (activityContainer) {
    setInterval(() => {
      if (!document.hidden) refreshActivityFromServer();
    }, 7000);
  }

  // =========================================================================
  // ── Trending Topics funcional: refresco en vivo + filtro del feed al clic ──
  // =========================================================================
  const trendingContainer = document.getElementById('trending-list-container');
  const trendingActiveFilter = document.getElementById('trending-active-filter');
  const trendingFilterLabel = document.getElementById('trending-filter-label');
  const trendingClearBtn = document.getElementById('trending-clear-filter-btn');

  // Estado del filtro activo aplicado sobre el feed
  let activeTrendFilter = null; // { tipo: 'categoria'|'hashtag', clave: string }

  // Construye un item de tendencia como nodo DOM
  function buildTrendingItem(topic) {
    const item = document.createElement('div');
    item.className = 'trending-item trending-clickable';
    item.dataset.trendTipo = topic.tipo;
    item.dataset.trendClave = topic.clave;
    // Marcar como activo si coincide con el filtro vigente
    if (activeTrendFilter && activeTrendFilter.tipo === topic.tipo &&
        String(activeTrendFilter.clave).toLowerCase() === String(topic.clave).toLowerCase()) {
      item.classList.add('trending-item-active');
    }
    item.innerHTML = `
      <span class="trending-category">${escapeHtml(topic.categoria)}</span>
      <a href="#" class="trending-tag">${escapeHtml(topic.hashtag)}</a>
      <span class="trending-count">${escapeHtml(topic.detalle)}</span>
    `;
    return item;
  }

  // Reemplaza el contenido del widget de tendencias con los datos del servidor
  function renderTrendingList(topics) {
    if (!trendingContainer || !Array.isArray(topics)) return;
    trendingContainer.innerHTML = '';
    if (topics.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'trending-empty-state';
      empty.id = 'trending-empty-state';
      empty.innerHTML = '<span class="trending-count" style="color: var(--text-muted);">Aún no hay tendencias. Cuando lleguen reportes, aparecerán aquí.</span>';
      trendingContainer.appendChild(empty);
      return;
    }
    topics.forEach(t => trendingContainer.appendChild(buildTrendingItem(t)));
  }

  // Refresca las tendencias desde el servidor (fuente de verdad basada en publicaciones)
  async function refreshTrendingFromServer() {
    if (!trendingContainer) return;
    try {
      const res = await fetch('/feed/api/trending-topics/', {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'ok' && Array.isArray(data.trending_topics)) {
        renderTrendingList(data.trending_topics);
      }
    } catch (_) {}
  }

  // Aplica el filtro sobre las tarjetas del feed mostrando/ocultando según coincidencia
  function applyTrendFilter(tipo, clave) {
    if (!feedStreamContainer) return;
    activeTrendFilter = { tipo, clave };

    const cards = feedStreamContainer.querySelectorAll('.post-card');
    let visibles = 0;
    cards.forEach(card => {
      let coincide = false;
      if (tipo === 'categoria') {
        coincide = (card.dataset.categoria || '').toUpperCase() === String(clave).toUpperCase();
      } else if (tipo === 'hashtag') {
        const texto = (card.dataset.texto || '').toLowerCase();
        coincide = texto.includes('#' + String(clave).toLowerCase());
      }
      card.style.display = coincide ? '' : 'none';
      if (coincide) visibles++;
    });

    // Mostrar aviso de filtro activo
    if (trendingActiveFilter && trendingFilterLabel) {
      const etiqueta = tipo === 'hashtag' ? '#' + clave : clave;
      trendingFilterLabel.textContent = `Filtrando por ${etiqueta} · ${visibles} resultado${visibles === 1 ? '' : 's'}`;
      trendingActiveFilter.classList.remove('d-none');
    }

    // Resaltar el item activo en el widget
    if (trendingContainer) {
      trendingContainer.querySelectorAll('.trending-item').forEach(it => {
        const match = it.dataset.trendTipo === tipo &&
          String(it.dataset.trendClave).toLowerCase() === String(clave).toLowerCase();
        it.classList.toggle('trending-item-active', match);
      });
    }

    if (typeof showToast === 'function') {
      showToast(visibles > 0 ? `Mostrando ${visibles} publicación${visibles === 1 ? '' : 'es'}` : 'No hay publicaciones para esta tendencia');
    }
  }

  // Limpia el filtro y vuelve a mostrar todas las publicaciones
  function clearTrendFilter() {
    activeTrendFilter = null;
    if (feedStreamContainer) {
      feedStreamContainer.querySelectorAll('.post-card').forEach(card => {
        card.style.display = '';
      });
    }
    if (trendingActiveFilter) trendingActiveFilter.classList.add('d-none');
    if (trendingContainer) {
      trendingContainer.querySelectorAll('.trending-item').forEach(it => it.classList.remove('trending-item-active'));
    }
  }

  // Clic en una tendencia → filtrar el feed (toggle si ya está activa)
  if (trendingContainer) {
    trendingContainer.addEventListener('click', (e) => {
      const item = e.target.closest('.trending-clickable');
      if (!item) return;
      e.preventDefault();
      const tipo = item.dataset.trendTipo;
      const clave = item.dataset.trendClave;
      if (!tipo || !clave) return;

      // Si se hace clic en la tendencia ya activa, se limpia (toggle)
      if (activeTrendFilter && activeTrendFilter.tipo === tipo &&
          String(activeTrendFilter.clave).toLowerCase() === String(clave).toLowerCase()) {
        clearTrendFilter();
      } else {
        applyTrendFilter(tipo, clave);
      }
    });
  }

  if (trendingClearBtn) {
    trendingClearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      clearTrendFilter();
    });
  }

  // Refresco periódico de tendencias (cada 15s). No reaplica el filtro para no
  // sorprender al usuario mientras navega; solo actualiza los conteos visibles.
  if (trendingContainer) {
    setInterval(() => {
      if (!document.hidden && !activeTrendFilter) refreshTrendingFromServer();
    }, 15000);
  }

  // =========================================================================
  // ── 9. Módulo de Búsqueda Avanzada y Filtros (RF-008 & Interfaz INT-003) ──
  // =========================================================================
  const feedNormalSection = document.getElementById('feed-normal-section');
  const feedSearchSection = document.getElementById('feed-search-section');
  const searchModeBackBtn = document.getElementById('searchModeBackBtn');
  const searchExpandedInput = document.getElementById('searchExpandedInput');
  const searchExpandedClearBtn = document.getElementById('searchExpandedClearBtn');
  const widgetSearchBar = document.getElementById('widget-search-bar');
  const widgetSearchInput = document.getElementById('widgetSearchInput');
  const widgetTrendingTopics = document.getElementById('widget-trending-topics');
  const widgetSearchTabs = document.getElementById('widget-search-tabs');
  const widgetSearchFilters = document.getElementById('widget-search-filters');
  const searchEmptyState = document.getElementById('search-empty-state');
  const searchEmptyDesc = document.getElementById('searchEmptyDesc');
  const btnClearSearchAll = document.getElementById('btnClearSearchAll');

  const filterDateInput = document.getElementById('filterDateInput');
  const filterDateLabel = document.getElementById('filterDateLabel');
  const filterDateClearBtn = document.getElementById('filterDateClearBtn');
  const filterDateBtn = document.getElementById('filterDateBtn');

  // Estado del sistema de búsqueda
  let isSearchActive = false;
  let currentSearchQuery = '';
  let currentSearchTab = 'historico';
  let currentSearchPersonas = 'todas';
  let currentSearchUbicacion = 'cercano';
  let currentSearchDate = '';
  let serverSearchDebounceTimer = null;
  let activeSearchAbortController = null;

  // Protocolo de seguridad: sanitización de entrada de búsqueda
  function sanitizeSearchInput(raw) {
    if (!raw) return '';
    // Truncar a longitud máxima segura (150 caracteres)
    let sanitized = String(raw).slice(0, 150);
    // Eliminar caracteres nulos y de control ASCII
    sanitized = sanitized.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
    // Eliminar cualquier intento de inyección de etiquetas HTML o scripts
    sanitized = sanitized.replace(/<[^>]*>/g, '');
    return sanitized;
  }

  // Activa el modo de búsqueda en la interfaz
  function enterSearchMode(initialQuery = '') {
    if (!feedSearchSection) return;
    isSearchActive = true;

    if (feedNormalSection) feedNormalSection.classList.add('d-none');
    feedSearchSection.classList.remove('d-none');

    if (widgetSearchBar) widgetSearchBar.classList.add('d-none');
    if (widgetTrendingTopics) widgetTrendingTopics.classList.add('d-none');
    if (widgetSearchTabs) widgetSearchTabs.classList.remove('d-none');
    if (widgetSearchFilters) widgetSearchFilters.classList.remove('d-none');

    const cleanInitial = sanitizeSearchInput(initialQuery);
    if (searchExpandedInput) {
      searchExpandedInput.value = cleanInitial;
      currentSearchQuery = cleanInitial;
    }

    if (searchExpandedClearBtn) {
      searchExpandedClearBtn.classList.toggle('d-none', !currentSearchQuery);
    }

    if (searchExpandedInput) {
      setTimeout(() => searchExpandedInput.focus(), 60);
    }

    runSearchFilter();
  }

  // Desactiva el modo de búsqueda y restablece el feed normal
  function exitSearchMode() {
    if (!feedSearchSection) return;
    isSearchActive = false;

    // Cancelar cualquier petición de búsqueda en vuelo
    if (activeSearchAbortController) {
      activeSearchAbortController.abort();
      activeSearchAbortController = null;
    }

    feedSearchSection.classList.add('d-none');
    if (feedNormalSection) feedNormalSection.classList.remove('d-none');

    if (widgetSearchTabs) widgetSearchTabs.classList.add('d-none');
    if (widgetSearchFilters) widgetSearchFilters.classList.add('d-none');
    if (widgetSearchBar) widgetSearchBar.classList.remove('d-none');
    if (widgetTrendingTopics) widgetTrendingTopics.classList.remove('d-none');

    if (searchExpandedInput) searchExpandedInput.value = '';
    if (widgetSearchInput) widgetSearchInput.value = '';
    currentSearchQuery = '';

    if (filterDateInput) filterDateInput.value = '';
    if (filterDateLabel) {
      filterDateLabel.textContent = 'Buscar por fecha';
      filterDateLabel.classList.remove('has-date');
    }
    if (filterDateClearBtn) filterDateClearBtn.classList.add('d-none');
    currentSearchDate = '';

    if (searchEmptyState) searchEmptyState.classList.add('d-none');

    // Ocultar sección de comentarios encontrados de búsqueda
    const searchCommentsStream = document.getElementById('search-comments-stream');
    const searchCommentsList = document.getElementById('searchCommentsList');
    if (searchCommentsStream) searchCommentsStream.classList.add('d-none');
    if (searchCommentsList) searchCommentsList.innerHTML = '';

    // Mostrar todas las tarjetas del feed y retirar resaltados en comentarios
    if (feedStreamContainer) {
      feedStreamContainer.querySelectorAll('.post-card').forEach(card => {
        card.style.display = '';
        card.querySelectorAll('.comment-search-match').forEach(c => c.classList.remove('comment-search-match'));
      });
    }
  }

  // Normalización para búsqueda por similitudes (ignora mayúsculas, minúsculas, tildes y diacríticos)
  function removeAccents(str) {
    if (!str) return '';
    return String(str)
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .toLowerCase()
      .trim();
  }

  // Navegación fluida estilo Twitter/X: Al hacer clic en un comentario encontrado,
  // sale de búsqueda, despliega los comentarios del reporte correspondiente y enfoca el comentario con un pulso
  function navigateToCommentFromSearch(postId, commentId) {
    if (!postId) return;
    exitSearchMode();

    setTimeout(() => {
      const postCard = document.getElementById(`post-card-${postId}`);
      if (!postCard) return;

      // Desplegar comentarios si están colapsados
      const commentsSection = postCard.querySelector('.post-comments-section');
      if (commentsSection) {
        commentsSection.classList.remove('collapsed');
        commentsSection.style.display = 'block';
      }

      // Si es respuesta anidada, asegurar que el contenedor de respuestas esté visible
      const targetComment = document.getElementById(`comment-card-${commentId}`);
      if (targetComment) {
        const parentThread = targetComment.closest('.comment-replies-thread');
        if (parentThread) {
          parentThread.style.display = 'block';
        }

        // Scroll suave y centrado al comentario específico
        targetComment.scrollIntoView({ behavior: 'smooth', block: 'center' });

        // Animación de foco pulsante
        targetComment.classList.remove('comment-focus-pulse');
        void targetComment.offsetWidth; // Forzar reflow para reiniciar la animación
        targetComment.classList.add('comment-focus-pulse');
        setTimeout(() => {
          targetComment.classList.remove('comment-focus-pulse');
        }, 3200);

        // Actualizar URL hash de forma limpia
        if (window.history && window.history.replaceState) {
          window.history.replaceState(null, '', `#comment-card-${commentId}`);
        }
      } else {
        postCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 100);
  }

  // Filtrado reactivo en tiempo real de publicaciones Y comentarios
  function runSearchFilter() {
    if (!feedStreamContainer) return;

    const rawTerms = currentSearchQuery.trim().split(/\s+/).filter(Boolean);
    const normalizedTerms = rawTerms.map(t => removeAccents(t));
    const cards = Array.from(feedStreamContainer.querySelectorAll('.post-card'));
    
    const searchCommentsStream = document.getElementById('search-comments-stream');
    const searchCommentsList = document.getElementById('searchCommentsList');
    const searchCommentsCountBadge = document.getElementById('searchCommentsCountBadge');

    let visiblePostsCount = 0;
    const matchingComments = [];

    cards.forEach(card => {
      let visible = true;

      // 1. Filtro por palabras clave (insensible a tildes / acentos)
      if (normalizedTerms.length > 0) {
        const fullPostText = removeAccents(card.dataset.texto || '');
        const postMatches = normalizedTerms.every(term => fullPostText.includes(term));

        // Inspeccionar comentarios y respuestas del post
        const commentElements = card.querySelectorAll('.comment-card, .reply-card');
        commentElements.forEach(cCard => {
          const cText = removeAccents(cCard.dataset.commentText || '');
          const cAuthor = removeAccents(cCard.dataset.commentAuthor || '');
          const commentFull = `${cAuthor} ${cText}`;
          const cMatches = normalizedTerms.every(term => commentFull.includes(term));

          if (cMatches) {
            cCard.classList.add('comment-search-match');
            matchingComments.push({
              id: cCard.dataset.commentId,
              postId: cCard.dataset.postId || card.id.replace('post-card-', ''),
              postTitle: cCard.dataset.postTitle || card.querySelector('.post-title, .badge-categoria')?.textContent?.trim() || 'Incidencia comunitaria',
              postAuthor: cCard.dataset.postAuthor || card.querySelector('.author-name')?.textContent?.trim() || 'vecino',
              commentAuthor: cCard.dataset.commentAuthor || 'Vecino',
              commentUsername: cCard.dataset.commentUsername || '',
              commentAvatar: cCard.dataset.commentAvatar || '',
              commentTime: cCard.dataset.commentTime || 'Hace un momento',
              commentText: cCard.dataset.commentText || '',
              parentAuthor: cCard.dataset.parentAuthor || '',
            });
          } else {
            cCard.classList.remove('comment-search-match');
          }
        });

        // REQUISITO CLAVE:
        // Si el término solo coincide en un comentario, NO mostrar la publicación completa en el feed.
        // La tarjeta de publicación completa solo aparece si su PROPIO contenido coincide.
        if (!postMatches) {
          visible = false;
        }
      } else {
        // Sin término de búsqueda: limpiar resaltados en comentarios
        card.querySelectorAll('.comment-search-match').forEach(c => c.classList.remove('comment-search-match'));
      }

      // 2. Filtro por fecha (RF-008)
      if (visible && currentSearchDate) {
        const cardDate = (card.dataset.fecha || '').trim();
        if (cardDate !== currentSearchDate) visible = false;
      }

      // 3. Filtro por Pestañas: Media
      if (visible && currentSearchTab === 'media') {
        const hasMedia = card.dataset.hasMedia === 'true';
        if (!hasMedia) visible = false;
      }

      // 4. Filtro por Personas
      if (visible && currentSearchPersonas === 'cercanas') {
        const isOwn = card.dataset.isOwn === 'true';
        const hasCoords = Boolean(card.dataset.lat && card.dataset.lng);
        if (!isOwn && !hasCoords) visible = false;
      }

      // 5. Filtro por Ubicación
      if (visible && currentSearchUbicacion === 'cercano') {
        const hasCoords = Boolean(card.dataset.lat && card.dataset.lng);
        if (!hasCoords && !card.dataset.texto.includes('calle') && !card.dataset.texto.includes('avenida')) {
          // prioridad
        }
      }

      card.style.display = visible ? '' : 'none';
      if (visible) visiblePostsCount++;
    });

    // Renderizar tarjetas individuales de comentarios estilo Twitter/X
    if (searchCommentsStream && searchCommentsList) {
      if (matchingComments.length > 0 && normalizedTerms.length > 0) {
        searchCommentsList.innerHTML = matchingComments.map(c => `
          <div class="search-comment-card" data-post-id="${c.postId}" data-comment-id="${c.id}" role="button" tabindex="0">
            <div class="search-comment-context">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="9 17 4 12 9 7"></polyline>
                <path d="M20 18v-2a4 4 0 0 0-4-4H4"></path>
              </svg>
              <span class="search-comment-context-text">
                En respuesta a <strong class="context-author">@${escapeHtml(c.postAuthor)}</strong>
                <span class="search-comment-dot">&bull;</span>
                <span class="context-title">${escapeHtml(c.postTitle)}</span>
                ${c.parentAuthor ? `<span class="search-comment-dot">&bull;</span> <span style="color:#64748b;">(en hilo de @${escapeHtml(c.parentAuthor)})</span>` : ''}
              </span>
            </div>
            
            <div class="search-comment-main">
              <div class="search-comment-avatar">
                ${c.commentAvatar ? 
                  `<img src="${c.commentAvatar}" alt="${escapeHtml(c.commentAuthor)}" class="search-comment-avatar-img">` :
                  `<div class="search-comment-avatar-placeholder">${escapeHtml(c.commentAuthor.slice(0, 2).toUpperCase())}</div>`
                }
              </div>
              <div class="search-comment-body">
                <div class="search-comment-meta">
                  <span class="search-comment-author-name">${escapeHtml(c.commentAuthor)}</span>
                  ${c.commentUsername ? `<span class="search-comment-handle">@${escapeHtml(c.commentUsername)}</span>` : ''}
                  <span class="search-comment-dot">&bull;</span>
                  <span class="search-comment-timestamp">${escapeHtml(c.commentTime)}</span>
                </div>
                <p class="search-comment-text">${escapeHtml(c.commentText)}</p>
                <div class="search-comment-footer">
                  <span class="search-comment-jump-hint">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                      <polyline points="15 3 21 3 21 9"></polyline>
                      <line x1="10" y1="14" x2="21" y2="3"></line>
                    </svg>
                    Ver publicación completa
                  </span>
                </div>
              </div>
            </div>
          </div>
        `).join('');

        if (searchCommentsCountBadge) {
          searchCommentsCountBadge.textContent = matchingComments.length;
        }
        searchCommentsStream.classList.remove('d-none');
      } else {
        searchCommentsList.innerHTML = '';
        searchCommentsStream.classList.add('d-none');
      }
    }

    const totalMatches = visiblePostsCount + (normalizedTerms.length > 0 ? matchingComments.length : 0);

    // Ordenamiento por pestañas: 'recientes' (más nuevos primero) vs 'historico'
    if (currentSearchTab === 'recientes') {
      const sortedCards = cards.filter(c => c.style.display !== 'none').sort((a, b) => {
        const tA = parseInt(a.dataset.timestamp || '0', 10);
        const tB = parseInt(b.dataset.timestamp || '0', 10);
        return tB - tA;
      });
      sortedCards.forEach(c => feedStreamContainer.appendChild(c));
    }

    // Manejo del estado vacío con prevención XSS estricta
    if (searchEmptyState) {
      if (totalMatches === 0) {
        if (searchEmptyDesc) {
          if (currentSearchQuery) {
            // Uso seguro de escapeHtml para evitar XSS
            searchEmptyDesc.innerHTML = `No se encontraron incidencias ni comentarios para "<strong>${escapeHtml(currentSearchQuery)}</strong>".`;
          } else if (currentSearchDate) {
            searchEmptyDesc.textContent = `No hay reportes registrados para la fecha ${currentSearchDate}.`;
          } else {
            searchEmptyDesc.textContent = 'No hay publicaciones ni comentarios que cumplan con los filtros seleccionados.';
          }
        }
        searchEmptyState.classList.remove('d-none');
      } else {
        searchEmptyState.classList.add('d-none');
      }
    }

    // Búsqueda en servidor con debounce y control de concurrencia
    triggerServerSearch();
  }

  // Delegación de eventos para clics en tarjetas de comentarios estilo Twitter
  const searchCommentsListEl = document.getElementById('searchCommentsList');
  if (searchCommentsListEl) {
    searchCommentsListEl.addEventListener('click', (e) => {
      const card = e.target.closest('.search-comment-card');
      if (!card) return;
      const postId = card.dataset.postId;
      const commentId = card.dataset.commentId;
      navigateToCommentFromSearch(postId, commentId);
    });

    searchCommentsListEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        const card = e.target.closest('.search-comment-card');
        if (card) {
          e.preventDefault();
          navigateToCommentFromSearch(card.dataset.postId, card.dataset.commentId);
        }
      }
    });
  }

  // Búsqueda en backend con AbortController, rate limiting y debounce
  function triggerServerSearch() {
    clearTimeout(serverSearchDebounceTimer);
    if (!currentSearchQuery && !currentSearchDate && currentSearchTab === 'historico') return;

    serverSearchDebounceTimer = setTimeout(async () => {
      // Cancelar petición anterior para evitar condiciones de carrera
      if (activeSearchAbortController) {
        activeSearchAbortController.abort();
      }
      activeSearchAbortController = new AbortController();

      try {
        const params = new URLSearchParams({
          q: currentSearchQuery,
          tab: currentSearchTab,
          personas: currentSearchPersonas,
          ubicacion: currentSearchUbicacion,
          fecha: currentSearchDate,
        });

        const res = await fetch(`/feed/api/buscar/?${params.toString()}`, {
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
          signal: activeSearchAbortController.signal,
        });

        // Protocolo de seguridad: Manejo de Rate Limiting 429
        if (res.status === 429) {
          const errData = await res.json().catch(() => ({}));
          if (typeof showToast === 'function') {
            showToast(errData.message || 'Has alcanzado el límite de búsquedas por minuto. Espera un momento.', true);
          }
          return;
        }

        if (!res.ok) return;
        const data = await res.json();

        if (data.status === 'ok') {
          const serverPosts = data.count || 0;
          const serverComments = (data.comentarios && data.comentarios.length) || 0;

          // Si el servidor encontró comentarios que no estaban cargados en el DOM inicial, incorporarlos
          if (serverComments > 0 && searchCommentsListEl) {
            const existingCommentIds = new Set(
              Array.from(searchCommentsListEl.querySelectorAll('.search-comment-card')).map(c => c.dataset.commentId)
            );
            const newServerComments = data.comentarios.filter(c => !existingCommentIds.has(String(c.id)));
            if (newServerComments.length > 0) {
              const extraCardsHtml = newServerComments.map(c => `
                <div class="search-comment-card" data-post-id="${c.post_id}" data-comment-id="${c.id}" role="button" tabindex="0">
                  <div class="search-comment-context">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="9 17 4 12 9 7"></polyline>
                      <path d="M20 18v-2a4 4 0 0 0-4-4H4"></path>
                    </svg>
                    <span class="search-comment-context-text">
                      En respuesta a <strong class="context-author">@${escapeHtml(c.post_author)}</strong>
                      <span class="search-comment-dot">&bull;</span>
                      <span class="context-title">${escapeHtml(c.post_title)}</span>
                      ${c.parent_author ? `<span class="search-comment-dot">&bull;</span> <span style="color:#64748b;">(en hilo de @${escapeHtml(c.parent_author)})</span>` : ''}
                    </span>
                  </div>
                  
                  <div class="search-comment-main">
                    <div class="search-comment-avatar">
                      ${c.comment_avatar ? 
                        `<img src="${c.comment_avatar}" alt="${escapeHtml(c.comment_author)}" class="search-comment-avatar-img">` :
                        `<div class="search-comment-avatar-placeholder">${escapeHtml(c.comment_author.slice(0, 2).toUpperCase())}</div>`
                      }
                    </div>
                    <div class="search-comment-body">
                      <div class="search-comment-meta">
                        <span class="search-comment-author-name">${escapeHtml(c.comment_author)}</span>
                        ${c.comment_username ? `<span class="search-comment-handle">@${escapeHtml(c.comment_username)}</span>` : ''}
                        <span class="search-comment-dot">&bull;</span>
                        <span class="search-comment-timestamp">${escapeHtml(c.comment_time)}</span>
                      </div>
                      <p class="search-comment-text">${escapeHtml(c.comment_text)}</p>
                      <div class="search-comment-footer">
                        <span class="search-comment-jump-hint">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                          </svg>
                          Ver publicación completa
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              `).join('');
              searchCommentsListEl.insertAdjacentHTML('beforeend', extraCardsHtml);
              const searchCommentsStream = document.getElementById('search-comments-stream');
              if (searchCommentsStream) searchCommentsStream.classList.remove('d-none');
              const searchCommentsCountBadge = document.getElementById('searchCommentsCountBadge');
              if (searchCommentsCountBadge) {
                const total = searchCommentsListEl.querySelectorAll('.search-comment-card').length;
                searchCommentsCountBadge.textContent = total;
              }
            }
          }

          if (serverPosts === 0 && serverComments === 0 && (!feedStreamContainer || feedStreamContainer.querySelectorAll('.post-card[style=""]').length === 0)) {
            if (searchEmptyState) searchEmptyState.classList.remove('d-none');
          } else {
            if (searchEmptyState) searchEmptyState.classList.add('d-none');
          }
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          console.error('Error en búsqueda:', err);
        }
      }
    }, 280);
  }

  // Eventos para abrir el modo de búsqueda con sanitización.
  // Si esta página NO tiene la sección de búsqueda del feed (p. ej. notificaciones,
  // perfil, mapa), el buscador redirige al feed comunitario con ?q=... para que
  // allí se active el modo búsqueda al cargar.
  if (widgetSearchInput) {
    const irAlFeedConBusqueda = (q) => {
      const query = (q || '').trim();
      const base = widgetSearchInput.dataset.feedUrl || '/feed/';
      const destino = query
        ? `${base}?q=${encodeURIComponent(query)}`
        : `${base}?busqueda=1`;
      window.location.href = destino;
    };

    if (!feedSearchSection) {
      // Página sin feed: enfocar/escribir manda al feed a buscar.
      widgetSearchInput.addEventListener('focus', () => irAlFeedConBusqueda(widgetSearchInput.value));
      widgetSearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          irAlFeedConBusqueda(widgetSearchInput.value);
        }
      });
    } else {
      widgetSearchInput.addEventListener('focus', () => {
        enterSearchMode(widgetSearchInput.value);
      });
      widgetSearchInput.addEventListener('click', () => {
        enterSearchMode(widgetSearchInput.value);
      });
      widgetSearchInput.addEventListener('input', (e) => {
        enterSearchMode(e.target.value);
      });
    }
  }

  // Botón de búsqueda en móvil/tablet (visible cuando el panel derecho está oculto)
  const mobileSearchTriggerBtn = document.getElementById('mobileSearchTriggerBtn');
  if (mobileSearchTriggerBtn) {
    mobileSearchTriggerBtn.addEventListener('click', (e) => {
      e.preventDefault();
      enterSearchMode('');
    });
  }

  // Evento para volver al feed normal (← Busqueda)
  if (searchModeBackBtn) {
    searchModeBackBtn.addEventListener('click', (e) => {
      e.preventDefault();
      exitSearchMode();
    });
  }

  // Input de búsqueda extendida en tiempo real con sanitización
  if (searchExpandedInput) {
    searchExpandedInput.addEventListener('input', (e) => {
      currentSearchQuery = sanitizeSearchInput(e.target.value);
      if (searchExpandedClearBtn) {
        searchExpandedClearBtn.classList.toggle('d-none', !currentSearchQuery);
      }
      runSearchFilter();
    });

    searchExpandedInput.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        exitSearchMode();
      }
    });
  }

  // Botón limpiar input de búsqueda
  if (searchExpandedClearBtn) {
    searchExpandedClearBtn.addEventListener('click', () => {
      if (searchExpandedInput) {
        searchExpandedInput.value = '';
        currentSearchQuery = '';
        searchExpandedInput.focus();
      }
      searchExpandedClearBtn.classList.add('d-none');
      runSearchFilter();
    });
  }

  // Pestañas (Historico, Más recientes, Media) tanto en sidebar como en móvil
  document.querySelectorAll('#widget-search-tabs .search-tab-btn, #mobileSearchTabs .search-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.dataset.tab || 'historico';
      document.querySelectorAll('#widget-search-tabs .search-tab-btn, #mobileSearchTabs .search-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tab === targetTab);
      });
      currentSearchTab = targetTab;
      runSearchFilter();
    });
  });

  // Filtros de personas (Radios)
  document.querySelectorAll('input[name="filter_personas"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      currentSearchPersonas = e.target.value;
      runSearchFilter();
    });
  });

  // Filtros de ubicación (Radios)
  document.querySelectorAll('input[name="filter_ubicacion"]').forEach(radio => {
    radio.addEventListener('change', (e) => {
      currentSearchUbicacion = e.target.value;
      runSearchFilter();
    });
  });

  // Selector de fecha (Buscar por fecha)
  if (filterDateInput) {
    filterDateInput.addEventListener('change', (e) => {
      currentSearchDate = e.target.value;
      if (currentSearchDate) {
        const parts = currentSearchDate.split('-');
        if (parts.length === 3) {
          const meses = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
          const mesNom = meses[parseInt(parts[1], 10) - 1] || parts[1];
          if (filterDateLabel) {
            filterDateLabel.textContent = `${parts[2]} ${mesNom} ${parts[0]}`;
            filterDateLabel.classList.add('has-date');
          }
        }
        if (filterDateClearBtn) filterDateClearBtn.classList.remove('d-none');
      } else {
        if (filterDateLabel) {
          filterDateLabel.textContent = 'Buscar por fecha';
          filterDateLabel.classList.remove('has-date');
        }
        if (filterDateClearBtn) filterDateClearBtn.classList.add('d-none');
      }
      runSearchFilter();
    });
  }

  if (filterDateClearBtn) {
    filterDateClearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      if (filterDateInput) filterDateInput.value = '';
      currentSearchDate = '';
      if (filterDateLabel) {
        filterDateLabel.textContent = 'Buscar por fecha';
        filterDateLabel.classList.remove('has-date');
      }
      filterDateClearBtn.classList.add('d-none');
      runSearchFilter();
    });
  }

  if (filterDateBtn && filterDateInput) {
    filterDateBtn.addEventListener('click', () => {
      if (typeof filterDateInput.showPicker === 'function') {
        filterDateInput.showPicker();
      } else {
        filterDateInput.click();
      }
    });
  }

  // Botón restablecer todos los filtros en empty state
  if (btnClearSearchAll) {
    btnClearSearchAll.addEventListener('click', () => {
      if (searchExpandedInput) searchExpandedInput.value = '';
      currentSearchQuery = '';
      if (searchExpandedClearBtn) searchExpandedClearBtn.classList.add('d-none');

      if (filterDateInput) filterDateInput.value = '';
      currentSearchDate = '';
      if (filterDateLabel) {
        filterDateLabel.textContent = 'Buscar por fecha';
        filterDateLabel.classList.remove('has-date');
      }
      if (filterDateClearBtn) filterDateClearBtn.classList.add('d-none');

      if (widgetSearchTabs) {
        widgetSearchTabs.querySelectorAll('.search-tab-btn').forEach(b => {
          b.classList.toggle('active', b.dataset.tab === 'historico');
        });
      }
      currentSearchTab = 'historico';

      const radPersTodas = document.querySelector('input[name="filter_personas"][value="todas"]');
      if (radPersTodas) radPersTodas.checked = true;
      currentSearchPersonas = 'todas';

      const radUbicCercano = document.querySelector('input[name="filter_ubicacion"][value="cercano"]');
      if (radUbicCercano) radUbicCercano.checked = true;
      currentSearchUbicacion = 'cercano';

      runSearchFilter();
    });
  }

  // Activar modo búsqueda si la URL contiene ?busqueda=1 o ?q=...
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.has('busqueda') || urlParams.has('q')) {
    const qParam = urlParams.get('q') || '';
    enterSearchMode(qParam);
  }

  // ── Visor de imagen ampliada estilo Twitter / X ──
  const lightboxModal = document.getElementById('urImageLightbox');
  const lightboxImg = document.getElementById('urLightboxImg');
  const lightboxCloseBtn = document.getElementById('urLightboxClose');
  const lightboxOverlay = document.getElementById('urLightboxOverlay');
  const lightboxContainer = document.getElementById('urLightboxContainer');

  function openLightbox(src, alt) {
    if (!lightboxModal || !lightboxImg || !src) return;
    lightboxImg.src = src;
    lightboxImg.alt = alt || 'Evidencia urbana ampliada';
    lightboxImg.classList.remove('is-zoomed');
    lightboxModal.classList.add('active');
    lightboxModal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('lightbox-open');
    if (lightboxCloseBtn) {
      setTimeout(() => lightboxCloseBtn.focus(), 60);
    }
  }

  function closeLightbox() {
    if (!lightboxModal) return;
    lightboxModal.classList.remove('active');
    lightboxModal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('lightbox-open');
    if (lightboxImg) {
      lightboxImg.classList.remove('is-zoomed');
      setTimeout(() => {
        if (!lightboxModal.classList.contains('active')) {
          lightboxImg.src = '';
        }
      }, 250);
    }
  }

  window.openUrbanLightbox = openLightbox;
  window.closeUrbanLightbox = closeLightbox;

  // Clic en imagen de publicación:
  // Si está en el feed (dentro de .post-clickable), el navegador va a detalles y comentarios.
  // Si ya está en detalles y comentarios (sin .post-clickable), se amplía estilo Twitter...
  // EXCEPTO si la publicación o la imagen están censuradas (bloqueo estricto de seguridad).
  document.addEventListener('click', (e) => {
    // Si el usuario hace clic sobre controles interactivos ajenos a la foto, ignorar
    if (e.target.closest('button, input, textarea, a, .post-menu-wrapper, .post-actions, .new-comment-form')) return;

    const mediaContainer = e.target.closest('.post-media-container, .comment-media-container');
    const mediaImg = e.target.closest('.post-media-img, .comment-media-img');
    if (!mediaContainer && !mediaImg) return;

    // BLOQUEO DE SEGURIDAD: Si la publicación o la imagen están censuradas, PROHIBIDO ampliar
    const isCensored =
      (mediaContainer && (
        mediaContainer.classList.contains('is-censored-media') ||
        mediaContainer.closest('.is-censored') ||
        mediaContainer.closest('.is-censored-card') ||
        mediaContainer.closest('[data-censurado="true"]')
      )) ||
      (mediaImg && (
        mediaImg.classList.contains('popup-img-censored') ||
        mediaImg.closest('.popup-media-censored') ||
        mediaImg.closest('.is-censored') ||
        mediaImg.closest('.is-censored-media') ||
        mediaImg.closest('.is-censored-card') ||
        mediaImg.closest('[data-censurado="true"]')
      ));

    if (isCensored) {
      e.preventDefault();
      e.stopPropagation();
      showToast('Esta imagen ha sido censurada por moderación y no se puede ampliar.', true);
      return;
    }

    // Si es la imagen de una publicación en el feed principal (dentro de .post-clickable),
    // dejamos que el manejador existente lleve al usuario a detalles y comentarios.
    // (Las imágenes de comentarios están fuera de .post-clickable y siempre se pueden ampliar).
    if (e.target.closest('.post-clickable')) return;

    // Ampliar la imagen en el visor
    const targetImg = mediaImg || (mediaContainer ? mediaContainer.querySelector('img') : null);
    if (!targetImg || !targetImg.src) return;

    e.preventDefault();
    e.stopPropagation();
    openLightbox(targetImg.src, targetImg.alt || 'Evidencia urbana ampliada');
  });

  // Soporte de accesibilidad para teclado (Enter o Espacio en la imagen en vista detalle)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      const activeEl = document.activeElement;
      if (
        activeEl &&
        activeEl.classList.contains('is-expandable-media') &&
        !activeEl.classList.contains('is-censored-media') &&
        !activeEl.closest('.is-censored') &&
        !activeEl.closest('[data-censurado="true"]')
      ) {
        const img = activeEl.querySelector('img');
        if (img && img.src) {
          e.preventDefault();
          openLightbox(img.src, img.alt || 'Evidencia urbana ampliada');
        }
      }
    }
  });

  if (lightboxCloseBtn) {
    lightboxCloseBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeLightbox();
    });
  }

  if (lightboxOverlay) {
    lightboxOverlay.addEventListener('click', (e) => {
      e.preventDefault();
      closeLightbox();
    });
  }

  if (lightboxContainer) {
    lightboxContainer.addEventListener('click', (e) => {
      // Cierra si el clic fue en el fondo del contenedor fuera de la imagen
      if (e.target === lightboxContainer) {
        e.preventDefault();
        closeLightbox();
      }
    });
  }

  // Alternar zoom ampliado al hacer clic sobre la imagen en el visor (estilo Twitter)
  if (lightboxImg) {
    lightboxImg.addEventListener('click', (e) => {
      e.stopPropagation();
      lightboxImg.classList.toggle('is-zoomed');
    });
  }

  // Cerrar visor al presionar Escape
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && lightboxModal && lightboxModal.classList.contains('active')) {
      closeLightbox();
    }
  });

  // ── Autocompletado de menciones @username en publicaciones y comentarios ──
  (function initMentionAutocomplete() {
    let menuEl = null;
    let activeInput = null;
    let mentionStartIdx = -1;
    let items = [];
    let selectedIdx = 0;
    let debounceTimer = null;

    const MENTION_INPUT_SELECTOR = [
      'textarea',
      'input.new-comment-input',
      'input.inline-reply-input',
      'input.comment-input',
      'input.reply-input',
      '#radicarTitulo',
      '#radicarContenido',
      '#editPostTitulo',
      '#editPostContenido',
      '#editCommentTexto',
      'input[name="contenido"]',
      'input[name="titulo"]'
    ].join(', ');

    function ensureMenu() {
      if (!menuEl) {
        menuEl = document.createElement('div');
        menuEl.className = 'mention-autocomplete-menu';
        menuEl.hidden = true;
        document.body.appendChild(menuEl);
      }
      return menuEl;
    }

    function hideMenu() {
      if (menuEl) menuEl.hidden = true;
      activeInput = null;
      mentionStartIdx = -1;
      items = [];
    }

    function selectMention(username) {
      if (!activeInput || mentionStartIdx < 0) return;
      const val = activeInput.value || '';
      const cursor = typeof activeInput.selectionStart === 'number' ? activeInput.selectionStart : val.length;
      const before = val.slice(0, mentionStartIdx);
      const after = val.slice(cursor);
      const inserted = '@' + username + ' ';
      activeInput.value = before + inserted + after;
      const newPos = before.length + inserted.length;
      activeInput.focus();
      if (typeof activeInput.setSelectionRange === 'function') {
        activeInput.setSelectionRange(newPos, newPos);
      }
      hideMenu();
    }

    function positionMenu(inputEl) {
      if (!menuEl || !inputEl) return;
      const rect = inputEl.getBoundingClientRect();
      const menuHeight = menuEl.offsetHeight || 220;
      let top = rect.bottom + 6;
      if (top + menuHeight > window.innerHeight - 10 && rect.top > menuHeight + 12) {
        top = rect.top - menuHeight - 6;
      }
      const left = Math.min(window.innerWidth - 270, Math.max(8, rect.left));
      menuEl.style.top = `${Math.max(8, top)}px`;
      menuEl.style.left = `${left}px`;
    }

    function renderMenu(usuarios, inputEl) {
      const menu = ensureMenu();
      items = usuarios || [];
      if (!items.length) {
        hideMenu();
        return;
      }
      selectedIdx = 0;
      menu.innerHTML = items.map((u, idx) => {
        const av = u.avatar_url
          ? `<img src="${escapeHtml(u.avatar_url)}" alt="" class="mention-autocomplete-avatar">`
          : `<span class="mention-autocomplete-avatar">${escapeHtml(u.iniciales || 'UR')}</span>`;
        return `<button type="button" class="mention-autocomplete-item ${idx === 0 ? 'is-active' : ''}" data-username="${escapeHtml(u.username)}">
          ${av}
          <span class="mention-autocomplete-info">
            <span class="mention-autocomplete-name">${escapeHtml(u.nombre)}</span>
            <span class="mention-autocomplete-user">@${escapeHtml(u.username)}</span>
          </span>
        </button>`;
      }).join('');

      menu.hidden = false;
      positionMenu(inputEl);
    }

    document.addEventListener('mousedown', (e) => {
      if (menuEl && !menuEl.hidden) {
        const btn = e.target.closest('.mention-autocomplete-item');
        if (btn) {
          e.preventDefault();
          e.stopPropagation();
          selectMention(btn.dataset.username);
          return;
        }
        if (e.target !== activeInput) hideMenu();
      }
    });

    function evaluateInputForMention(el) {
      if (!el || typeof el.matches !== 'function' || !el.matches(MENTION_INPUT_SELECTOR)) return;
      const val = el.value || '';
      const cursor = typeof el.selectionStart === 'number' ? el.selectionStart : val.length;
      const textBefore = val.slice(0, cursor);
      // Detecta '@' al inicio o tras espacio/puntuación, seguido de 0 a 30 letras, números o símbolos
      const match = textBefore.match(/(?:^|[\s([{"'¡¿,;:])@([^\s@]{0,30})$/);
      if (!match) {
        hideMenu();
        return;
      }
      const query = match[1] || '';
      activeInput = el;
      mentionStartIdx = textBefore.lastIndexOf('@' + query);

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(async () => {
        try {
          const res = await fetch('/feed/api/menciones/?q=' + encodeURIComponent(query), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
          });
          if (!res.ok) return;
          const data = await res.json();
          if (data && data.status === 'ok' && activeInput === el) {
            renderMenu(data.usuarios, el);
          }
        } catch (_) {}
      }, 90);
    }

    document.addEventListener('input', (e) => {
      evaluateInputForMention(e.target);
    });

    document.addEventListener('keydown', (e) => {
      if (!menuEl || menuEl.hidden || !items.length) return;
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedIdx = (selectedIdx + 1) % items.length;
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedIdx = (selectedIdx - 1 + items.length) % items.length;
      } else if (e.key === 'Enter' || e.key === 'Tab') {
        if (items[selectedIdx]) {
          e.preventDefault();
          e.stopPropagation();
          selectMention(items[selectedIdx].username);
        }
        return;
      } else if (e.key === 'Escape') {
        hideMenu();
        return;
      } else {
        return;
      }
      menuEl.querySelectorAll('.mention-autocomplete-item').forEach((btn, idx) => {
        btn.classList.toggle('is-active', idx === selectedIdx);
      });
    }, true);
  })();

  // ── Sincronización de Notificaciones en vivo (Campana del Feed y Móvil) ──
  (function initNotificacionesLiveBadge() {
    const bellBadge = document.getElementById('notif-bell-badge');
    const mobileBadge = document.getElementById('mobileNavBadge');
    if (!bellBadge && !mobileBadge) return;

    let previousCount = null;
    let initialSyncDone = false;

    function renderBadge(badgeEl, count) {
      if (!badgeEl) return;
      if (count > 0) {
        badgeEl.textContent = count > 9 ? '9+' : String(count);
        badgeEl.style.display = 'flex';
      } else {
        badgeEl.style.display = 'none';
      }
    }

    function construirMensajeAviso(notif) {
      if (!notif) return 'Tienes una nueva notificación';
      const actor = notif.actor_nombre ? notif.actor_nombre.trim() : 'Un usuario';
      switch (notif.tipo) {
        case 'MENCION':
          return notif.comentario_id
            ? `${actor} te mencionó en un comentario`
            : `${actor} te mencionó en una publicación`;
        case 'COMENTARIO':
          return `${actor} comentó en tu publicación`;
        case 'RESPUESTA':
          return `${actor} respondió a tu comentario`;
        case 'LIKE':
          return notif.comentario_id
            ? `A ${actor} le gustó tu comentario`
            : `A ${actor} le gustó tu publicación`;
        case 'CAMBIO_ESTADO':
          if (notif.extra && notif.extra.indexOf('Declinado') !== -1) {
            return 'Tu reporte fue declinado por un administrador';
          }
          return 'Tu reporte cambió de estado';
        case 'SEGUIDOR':
          return `${actor} comenzó a seguirte`;
        case 'REPORTE_CONTENIDO':
          return 'Nuevo reporte de contenido para moderación';
        default:
          return `${actor}: ${notif.mensaje || 'Nueva notificación'}`;
      }
    }

    async function actualizarBadgeNotificaciones() {
      try {
        const res = await fetch('/api/notificaciones-no-leidas/', {
          headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        if (!res.ok) return;
        const data = await res.json();
        if (data && data.status === 'ok') {
          const count = Number(data.total_no_leidas) || 0;

          // Si llegaron nuevas notificaciones mientras navegaba, avisar con toast y animación
          if (initialSyncDone && previousCount !== null && count > previousCount) {
            [bellBadge, mobileBadge].forEach((b) => {
              if (b) {
                b.classList.remove('badge-pulse');
                void b.offsetWidth;
                b.classList.add('badge-pulse');
              }
            });
            if (typeof showToast === 'function') {
              const msg = construirMensajeAviso(data.ultima_notificacion);
              showToast(`🔔 ${msg}`);
            }
          }

          previousCount = count;
          initialSyncDone = true;

          renderBadge(bellBadge, count);
          renderBadge(mobileBadge, count);
        }
      } catch (e) {
        // Silencioso ante fallos transitorios
      }
    }

    actualizarBadgeNotificaciones();
    setInterval(() => {
      if (!document.hidden) actualizarBadgeNotificaciones();
    }, 15000);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) actualizarBadgeNotificaciones();
    });
  })();

});

// Auth View Interactions (Login, Registro, Recuperación)
document.addEventListener('DOMContentLoaded', () => {
  // Role selector dropdown logic
  const roleDropdown = document.querySelector('.role-select-dropdown');
  if (roleDropdown) {
    const roleBtn = roleDropdown.querySelector('.role-select-btn');
    const roleMenu = roleDropdown.querySelector('.role-menu');
    const roleLabel = roleDropdown.querySelector('.role-label');
    const hiddenRoleInput = document.querySelector('#id_tipo_usuario');

    if (roleBtn && roleMenu) {
      roleBtn.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        roleMenu.classList.toggle('show');
      });

      roleMenu.querySelectorAll('.role-menu-item').forEach(item => {
        item.addEventListener('click', () => {
          const val = item.getAttribute('data-value');
          const text = item.textContent.trim();
          if (roleLabel) roleLabel.textContent = text;
          if (hiddenRoleInput) hiddenRoleInput.value = val;
          roleMenu.classList.remove('show');
        });
      });

      document.addEventListener('click', (e) => {
        if (!roleDropdown.contains(e.target)) {
          roleMenu.classList.remove('show');
        }
      });
    }
  }

  // Manejo de clic en "¿Olvidaste tu contraseña?" (recuperación deshabilitada temporalmente)
  const forgotLink = document.getElementById('forgotPasswordLink') || document.querySelector('.forgot-link');
  const recoveryNotice = document.getElementById('recoveryDisabledNotice');
  const recoveryClose = document.getElementById('recoveryNoticeClose');

  if (forgotLink && recoveryNotice) {
    forgotLink.addEventListener('click', (e) => {
      e.preventDefault();
      recoveryNotice.style.display = 'flex';
      recoveryNotice.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
  }

  if (recoveryClose && recoveryNotice) {
    recoveryClose.addEventListener('click', () => {
      recoveryNotice.style.display = 'none';
    });
  }

  // Auto-dismiss alerts
  setTimeout(() => {
    document.querySelectorAll('.alert').forEach(alert => {
      alert.style.opacity = '0';
      alert.style.transform = 'translateY(-10px)';
      alert.style.transition = 'all 0.4s ease';
      setTimeout(() => alert.remove(), 400);
    });
  }, 4500);
});

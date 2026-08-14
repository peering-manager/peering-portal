const COLOUR_MODE_KEY = 'peeringportal-colour-mode';
// The portal stored the mode under this key before it followed the Peering Manager naming
const LEGACY_COLOUR_MODE_KEY = 'portal-theme';

function getPreferredColourMode() {
  const storedMode = localStorage.getItem(COLOUR_MODE_KEY) || localStorage.getItem(LEGACY_COLOUR_MODE_KEY);
  const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

  if (storedMode) {
    return storedMode;
  }

  return prefersDark ? 'dark' : 'light';
}

function getCurrentColourMode() {
  return document.documentElement.getAttribute('data-bs-theme') || 'light';
}

function setColourMode(mode, button, button_only = false) {
  if (!button_only) {
    document.documentElement.setAttribute('data-bs-theme', mode);
    localStorage.setItem(COLOUR_MODE_KEY, mode);
  }

  // The icon advertises the mode the button switches to, not the one in use
  if (mode === 'dark') {
    button.innerHTML = '<i class="bi bi-sun-fill"></i>';
  } else {
    button.innerHTML = '<i class="bi bi-moon-fill"></i>';
  }
}

document.documentElement.setAttribute('data-bs-theme', getPreferredColourMode());

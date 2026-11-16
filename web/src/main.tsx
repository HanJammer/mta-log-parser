import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource-variable/overpass';
import '@fontsource-variable/overpass-mono';
import './styles/tokens.css';
import './styles/base.css';
import './styles/ui.css';
import './styles/app.css';
import './i18n';
import './lib/prefs';
import { App } from './App';

const root = document.getElementById('root');
if (!root) throw new Error('#root not found');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

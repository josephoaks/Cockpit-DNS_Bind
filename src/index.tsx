import React from 'react';
import { createRoot } from 'react-dom/client';
import '@patternfly/patternfly/patternfly.css';  // <-- Fix this line
import "cockpit-dark-theme";
import { Application } from './app.jsx';
import './app.scss';

document.addEventListener("DOMContentLoaded", () => {
    createRoot(document.getElementById("app")!).render(<Application />);
});

# Kemmon Lodge React frontend

React with JavaScript and Vite. This is a starter page, not a completed lodge interface.

## Run locally
Install a supported Node.js version (20.19+ within Node 20, or 22.12+ and newer supported releases) and npm first.

From this frontend directory:

```sh
pnpm install
pnpm run dev
```

Open the address printed by Vite. Do not open index.html directly.

```sh
pnpm run build
pnpm run preview
```

Commit the generated package-lock.json after the first successful installation.

## Structure
- `src/main.jsx`: mounts React in index.html.
- `src/App.jsx`: top-level application component.
- `src/styles.css`: shared styles.
- `src/components/`: reusable controls and layouts.
- `src/pages/`: login, rooms, reservations, folio, and other page components.
- `src/services/`: communication with the Python API.
- `src/assets/`: imported images and other assets.
- `public/`: assets served without processing.

## Backend connection
The Vite development server forwards `/api` requests to `http://127.0.0.1:8000`. Implement matching `/api` endpoints in FastAPI. This development proxy does not start the backend. Configure the equivalent routing or permitted origins in production. Never put database credentials or backend secrets in React files or frontend environment variables.

## Next implementation
Build the login page, shared staff layout, and room management page. Enforce permissions in FastAPI; the frontend is not the security boundary.

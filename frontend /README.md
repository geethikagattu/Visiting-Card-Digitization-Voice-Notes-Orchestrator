# Frontend

React + Vite chat UI for the Visiting Card Digitization & Voice Notes Orchestrator.

## Local Development

```bash
cd "frontend "
npm install
npm run dev
```

## API Configuration

The app reads the backend URL from `VITE_API_URL`.

For local development, leave it unset and the Vite proxy will route `/chat` requests to `http://localhost:8000`.

For deployment, set:

```env
VITE_API_URL=https://visiting-card-digitization-voice-notes.onrender.com
```

## Render Deployment

Create a Render Static Site or Web Service for the frontend.

Suggested settings:

```text
Root Directory: frontend 
Build Command: npm install && npm run build
Publish Directory: dist
```

If Render does not accept the trailing space in the root directory, rename the folder locally to `frontend` before deploying.

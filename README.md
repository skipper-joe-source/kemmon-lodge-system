# Kemmon Lodge Management System

A web application for managing lodge rooms, reservations, guests, billing, housekeeping, bar sales, inventory, and management reports.

## Planned technologies
- Backend: Python with FastAPI
- Database: PostgreSQL
- Frontend: React with JavaScript and Vite
- Database models: SQLAlchemy
- Database migrations: Alembic

## First milestone
A receptionist can log in, reserve an available room, check in a guest, record charges and payments, and check the guest out. Housekeeping can then mark the room ready.

## Project structure
- `docs/`: requirements, workflows, data design, permissions, and page plans
- `backend/app/`: backend application code
- `backend/tests/`: tests for important business rules
- `frontend/`: React components, pages, and Vite configuration

## Current status
Dashboard, rooms, and reservations are implemented. Reservations and room occupancy use a local PostgreSQL API. Staff authentication and the remaining lodge modules are still planned. See `backend/README.md` for startup and connection details.

## Development setup (after implementing the application)
1. Create a Python virtual environment inside `backend/.venv`.
2. Install the backend project dependencies from `backend/pyproject.toml`.
3. Copy `.env.example` to `.env` locally and enter development configuration.
4. Configure application settings to load that root `.env` file explicitly.
5. Initialize Alembic and create reviewed database migrations.
6. Run migrations against your development PostgreSQL database.
7. Start FastAPI on port 8000 with endpoints under `/api`.
8. In `frontend/`, run `npm install` and `npm run dev` (requires supported Node.js and npm).
9. For deployment, build the frontend with `npm run build` and configure hosting/API routing.

See `frontend/README.md` for the React setup and directory guide.

Never commit real passwords, secrets, guest documents, or database backups.

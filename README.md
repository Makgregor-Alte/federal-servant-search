\# Federal Servant Search



Full-stack application for searching Brazilian Federal Executive public servant data.



\## Project Overview



This project provides a web interface for querying public servant records from the Brazilian Federal Executive branch.



The application is designed as a containerized full-stack system composed of:



\- PostgreSQL database

\- Flask REST API

\- Gunicorn WSGI server

\- Web frontend

\- Docker Compose orchestration



\## Main Features



\- Exact name search

\- Similar name search

\- Position/profession search

\- State (UF) search

\- Institution/agency search

\- Combined advanced filters

\- Paginated results

\- JSON API responses

\- Concurrent request handling

\- Input validation and error handling



\## Architecture



Frontend

&#x20;  |

&#x20;  | HTTP

&#x20;  v

Flask API + Gunicorn

&#x20;  |

&#x20;  v

PostgreSQL



\## Project Structure



federal-servant-search/

├── backend/

├── frontend/

├── db/

├── docs/

│   ├── architecture/

│   ├── daily/

│   ├── meetings/

│   └── reports/

├── docker-compose.yml

├── .env.example

├── .gitignore

└── README.md



\## Team



The project is developed by a team of four members using an agile workflow and GitHub for version control and task tracking.



\## Development



The complete application will be started using:



docker compose up --build



\## Status



Project initialization and architecture setup.


# Container diagram

This [C4 container diagram](https://c4model.com/diagrams/container) expands the
[system context diagram](SystemContextDiagram.md) to show Borrow'd's application
and data stores in production. The Upsun hosting boundary identifies where the
web application and database run; the media bucket is hosted separately by Wasabi.

```mermaid
flowchart TD
    user["Borrow'd member<br/>[Person]<br/>Shares and borrows items within groups"]

    subgraph borrowd["Borrow'd — Software system"]
        subgraph upsun["Upsun — Production hosting"]
            app["Web application<br/>[Container: Python / Django]<br/>Server-rendered UI; manages accounts, groups,<br/>items, borrowing, and notifications"]
            db["Application database<br/>[Container: PostgreSQL]<br/>Stores accounts, memberships, items,<br/>transactions, and notification data"]
        end
        media["Media storage<br/>[Container: Wasabi S3-compatible bucket]<br/>Stores item, profile, and group images"]
    end

    email["Upsun email service<br/>[External software system]<br/>Delivers account and notification emails"]
    sentry["Sentry<br/>[External software system]<br/>Collects application errors and diagnostics"]

    user -->|"Lists and borrows items via a web browser [HTTPS]"| app
    user -->|"Views images [HTTPS]"| media
    app -->|"Reads/writes data [PostgreSQL protocol]"| db
    app -->|"Stores/retrieves images [S3-compatible API / HTTPS]"| media
    app -->|"Sends account and notification emails [SMTP / port 25]"| email
    app -->|"Reports errors [HTTPS]"| sentry

    classDef personStyle fill:#e8e8e8,stroke:#333,color:#222
    classDef containerStyle fill:#fff9e6,stroke:#e8c83d,color:#685818
    classDef externalSystemStyle fill:#f4f4f4,stroke:#777,color:#333

    class user personStyle
    class app,db,media containerStyle
    class email,sentry externalSystemStyle
```

The production configuration uses Upsun's built-in SMTP service via
`PLATFORM_SMTP_HOST` on port 25; see
[`borrowd/config/prod/django.py`](../../borrowd/config/prod/django.py). The hosting
configuration is defined in [`.platform.app.yaml`](../../.platform.app.yaml) and
[`.platform/services.yaml`](../../.platform/services.yaml).

```mermaid
flowchart TD
    user["User"]
    app["Borrow'd — Django web app"]
    ses["AWS SES Email service"]
    sentry["Sentry Errors and diagnostics"]

    user -->|"Lists and borrows items via a web browser"| app
    app -->|"Notification emails"| ses
    app -->|"Reports errors"| sentry

    classDef userStyle fill:#e8e8e8,stroke:#333,color:#222
    classDef appStyle fill:#edf6ff,stroke:#63ace5,color:#245a87
    classDef serviceStyle fill:#fff9e6,stroke:#e8c83d,color:#685818

    class user userStyle
    class app appStyle
    class ses,sentry serviceStyle
```

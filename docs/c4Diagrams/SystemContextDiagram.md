# System context diagram

This [C4 system context diagram](https://c4model.com/diagrams/system-context) shows
Borrow'd, its members, and the external services it uses in production. See the
[container diagram](ContainerDiagram.md) for the application's internal structure.

```mermaid
flowchart TD
    user["Borrow'd member<br/>[Person]<br/>Shares and borrows items within groups"]
    app["Borrow'd<br/>[Software system]<br/>Enables peer-to-peer item lending within groups"]
    email["Upsun email service<br/>[External software system]<br/>Delivers account and notification emails"]
    sentry["Sentry<br/>[External software system]<br/>Collects application errors and diagnostics"]

    user -->|"Lists and borrows items via a web browser"| app
    app -->|"Sends account and notification emails"| email
    app -->|"Reports errors"| sentry

    classDef userStyle fill:#e8e8e8,stroke:#333,color:#222
    classDef appStyle fill:#edf6ff,stroke:#63ace5,color:#245a87
    classDef serviceStyle fill:#fff9e6,stroke:#e8c83d,color:#685818

    class user userStyle
    class app appStyle
    class email,sentry serviceStyle
```

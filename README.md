# Blog code examples

Runnable companions for [Nabh Patodi's writing](https://nabhpatodi.com/blog/). Each example lives in its own directory with the source, setup instructions, tests, and boundaries needed to understand it. Run commands from that example's directory; there is no shared application or dependency setup at the repository root.

| Article | Example | What it demonstrates |
| --- | --- | --- |
| [How to Track Background Job Progress in React and FastAPI](https://nabhpatodi.com/blog/how-to-track-background-job-progress-in-react-and-fastapi/) | [react-fastapi-background-jobs](react-fastapi-background-jobs/) | Persisted jobs, status polling, refresh recovery, and a downloadable result. |
| Approval Workflow Database Design: Requests, Versions and Review Tasks | [approval-workflow-postgresql](approval-workflow-postgresql/) | Submitted versions, review assignments, correction, reassignment, guarded decisions, and PostgreSQL concurrency tests. |

Start with the README inside the example you want to run. These are original teaching examples with deliberately limited scope; their READMEs explain what would need additional work in a deployed application.

Code in this repository is available under the [MIT license](LICENSE).

# Task list feature

The task list is paginated in the browser. The `TaskList` component reads
`status` and `page` from the URL and calls `GET /tasks`.
The `GET /tasks` handler forwards the page to `TaskRepository.list`. It
currently returns every status. The stored status enum is open, active, done.
The list page has a toolbar above the results and already supports search.
Task list end-to-end tests seed tasks in each status and use page navigation.
Changing a filter must reset the page to 1. Pagination must preserve filters.
Clearing all filters must restore the complete task list.

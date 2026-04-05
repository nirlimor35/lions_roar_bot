# Code Review Checklist

## Overview
Comprehensive checklist for conducting thorough code reviews to ensure quality, security, and maintainability.

## Review Categories

### Functionality
- [ ] Code does what it's supposed to do
- [ ] Edge cases are handled
- [ ] No obvious bugs or logic errors

### Code Quality
- [ ] Code is readable and well-structured
- [ ] Functions are small and focused
- [ ] Variable names are descriptive
- [ ] No code duplication
- [ ] Follows project conventions
- [ ] Scan for code smells, anti-patterns, and potential bugs
- [ ] Identify unused imports, variables, or dead code
- [ ] No magic numbers (use constants)
- [ ] Imports are formatted and sorted
- [ ] Internal functions/methods prefixed with _
- [ ] Safe dictionary access (e.g. .get(key, []) or [])
- [ ] super().__init__() called before setting attributes in classes
- [ ] Complex regex patterns explained with comments
- [ ] Explicit return values in error handlers (e.g. return None)

### Security
- [ ] No obvious security vulnerabilities (SQL injection, XSS, etc.)
- [ ] Input validation is present
- [ ] Check for hardcoded secrets, API keys, or passwords
- [ ] Sensitive data is handled properly

### Performance Analysis
- [ ] No obvious performance bottlenecks
- [ ] No inefficient algorithms or database queries
- [ ] Review memory usage patterns and potential leaks
- [ ] DynamoDB queries use batch operations where possible
- [ ] No staleTime used in frontend queries
- [ ] Use TTL cache for rarely changing data
- [ ] Prefer specific lookups (get_by_id) over fetching all and filtering

### Database (DynamoDB/PynamoDB):
- [ ] DynamoDB operations use AWSDynamoDB access layer (not direct PynamoDB calls)
- [ ] Batch operations respect hard limits (25 for writes, 100 for reads)
- [ ] Exponential backoff implemented for throughput exceptions
- [ ] No individual items exceed 400KB DynamoDB limit
- [ ] Hash keys and range keys properly indexed

### Authentication & Authorization:
- [ ]RBAC checked using role_access_control module
- [ ] Customer ID extracted from token, not request body
- [ ] MSSP tenant validation performed when applicable

### Logging & Observability:
- [ ] Loguru logger used (not standard Python logging)
- [ ] customer_id bound to logger context
- [ ] Exception traces captured with logger.opt(exception=True)
- [ ] No noisy/spammy logs (check loops/conditions)
- [ ] Log progress for long-running operations

### Testing:
- [ ] Pytest fixtures used for test setup
- [ ] Tests not skipped without valid reason/ticket
- [ ] Mock data looks realistic (valid ARNs, CVE IDs, logos)

### Code Style:
- [ ] snake_case for functions/variables, CamelCase for classes
- [ ] CAPITALIZED_SNAKE_CASE for constants
- [ ] No code comments (self-documenting code preferred per rules)
- [ ] Functions organized top-to-bottom (callers above callees)

### Frontend-Specific (React/JavaScript):
#### UI/UX & Design System:
- [ ] UI components use only design system elements (e.g., Documentation/)
- [ ] Filter menus should only show relevant options based on current state (UX)
- [ ] UI strings/labels should use constants where appropriate (e.g. "N/A")
- [ ] Use icons only by importing from frontend/src/icons/IconMapping.js
- [ ] Never use useEffect unless you manipulate the DOM or use an event listener

#### State Management & Data Fetching:
- [ ] React Query used
- [ ] Query keys from queryKeys.js used consistently
- [ ] No staleTime used (no longer needed)
- [ ] No useMemo or useCallback hooks used (unnecessary complexity)
- [ ] Mutations invalidate relevant queries on success
- [ ] Context API used only for cross-cutting concerns (not prop drilling alternative)
- [ ] Components split when exceeding reasonable size (~200-300 lines)
- [ ] Complex logic in useEffect/rendering extracted to helper functions
- [ ] Avoid complex chained array operations (map/filter/reduce) in a single line; break down for readability

#### Forms & Validation:
- [ ] Formik + Yup used for form handling
- [ ] Validation schema defined with clear error messages
- [ ] Required fields marked with descriptive validation messages
- [ ] Email/domain validation uses proper regex patterns

### Error Handling:
- [ ] Toast notifications for user-facing errors
- [ ] API errors caught and displayed meaningfully
- [ ] Loading states handled for async operations
- [ ] Edge cases (empty states, no data) have UI representations
- [ ] Failure modes defined (atomic vs best-effort)

# Prompt: JWT + RBAC Learning Project (Spring Boot 3.5 + JTE)

## Purpose of this document

This file is a **complete specification** for generating a Spring Boot learning project that demonstrates OAuth2 + JWT + role-based access control. It is written to be self-contained: paste it (or attach it) to any AI tool and the tool should have everything needed to produce a working project without external context.

The original project was generated in chunks across many turns of conversation, with many small course-corrections. This document collapses all those decisions into one place and **calls out the specific pitfalls that previously caused broken builds**. Read it once end to end before generating code.

---

## 1. What to build

A single Spring Boot application that simultaneously plays three OAuth2 roles in three separate packages:

1. **Authorization Server** — issues JWTs via the Authorization Code grant. Has a custom HTML login page (NOT Spring's default). Hardcoded users, no database.
2. **OAuth2 Client** — the browser-facing app. Initiates the Authorization Code flow, receives the JWT, stores it in the server-side session, serves protected HTML pages.
3. **Resource Server** — stateless `/api/**` endpoints. Validates incoming Bearer JWTs against the authorization server's public keys. Used by Bruno / Postman / curl.

Templates use **JTE (Java Template Engine)**. Storage is **in-memory only** (no database, no Redis). The blocklist for revoked tokens is a `ConcurrentHashMap` behind an interface, swappable for Redis later.

The project must be runnable with a single command:

```bash
mvn spring-boot:run
```

…and must support the full end-to-end browser flow plus a Bruno/Postman API testing flow.

---

## 2. Hard requirements (non-negotiable)

These are decisions that have already been made and must NOT be changed without explicit instruction.

| Decision | Value | Why |
|---|---|---|
| Java version | 21 (LTS) | Required by Spring Boot 3.5.x |
| Spring Boot version | **3.5.15** | Latest 3.5.x patch. Do NOT use Boot 4.x — Spring Authorization Server was being relocated in Boot 4 / Security 7 and the package paths are unstable. |
| Template engine | JTE 3.1.16 | Must use the `jte-spring-boot-starter-3` artifact AND the `jte-maven-plugin` for precompilation. |
| OAuth2 grant type | `authorization_code` | Modern OAuth 2.1 standard. NOT `password` grant (deprecated). |
| Token type | JWT (signed, NOT opaque) | The whole demo is about JWTs. |
| Blocklist storage | In-memory `ConcurrentHashMap` | Wrapped in a `TokenBlocklist` service. Must be designed so the implementation could be swapped for Redis without changing callers. |
| Persistence | None | No database. Users, registered OAuth2 clients, and the blocklist all live in memory. |
| Build tool | Maven | Not Gradle. |
| Architecture | Single Spring Boot process | All three roles in one app, separated by package. NOT three separate processes. |

---

## 3. Tech stack (exact dependencies)

These go into `pom.xml`. Versions are managed by the Spring Boot parent except where noted.

```
spring-boot-starter-parent:3.5.15  (parent POM)

Dependencies (BOM-managed unless versioned):
  spring-boot-starter-web
  spring-boot-starter-security
  spring-boot-starter-oauth2-authorization-server
  spring-boot-starter-oauth2-client
  spring-boot-starter-oauth2-resource-server
  gg.jte:jte:3.1.16
  gg.jte:jte-spring-boot-starter-3:3.1.16
  spring-boot-starter-test (test scope)
  spring-security-test (test scope)

Plugins:
  spring-boot-maven-plugin
  gg.jte:jte-maven-plugin:3.1.16
    sourceDirectory: ${project.basedir}/src/main/jte
    contentType: Html
    phase: generate-sources
    goal: generate
```

---

## 4. Package layout (exact)

```
src/main/java/com/example/jwtdemo/
├── JwtDemoApplication.java                    (entry point + startup banner)
├── authserver/
│   ├── AuthServerConfig.java                  (two filter chains: protocol + login)
│   ├── UserConfig.java                        (hardcoded users + PasswordEncoder)
│   ├── TokenCustomizerConfig.java             (adds 'roles' claim to JWT)
│   └── AuthLoginController.java               (GET /login → login.jte)
├── client/
│   ├── ClientSecurityConfig.java              (oauth2Login + custom logout + blocklist handler)
│   └── PageController.java                    (/, /dashboard, /admin, /user, /logout-page)
└── resource/
    ├── ResourceSecurityConfig.java            (Bearer JWT, blocklist validator)
    ├── ApiController.java                     (/api/whoami, /api/admin/**, /api/user/**)
    ├── RoleClaimConverter.java                (JWT 'roles' → ROLE_* authorities)
    ├── BlocklistJwtValidator.java             (rejects revoked tokens)
    └── TokenBlocklist.java                    (in-memory ConcurrentHashMap)

src/main/jte/                                  (JTE templates — see Section 8)
src/main/resources/
├── application.yml                            (see Section 7)
└── static/css/style.css                       (minimal styling)
```

Other directories (e.g. `docs/`) are optional and contain READMEs for testing.

---

## 5. Filter chain ordering (CRITICAL — get this wrong and nothing works)

The single Spring Boot process needs **four separate `SecurityFilterChain` beans**, in this exact order:

| Order | Bean | Path matcher | Purpose |
|---|---|---|---|
| 1 | `authorizationServerFilterChain` | `OAuth2AuthorizationServerConfigurer.getEndpointsMatcher()` | OAuth2 / OIDC protocol endpoints (`/oauth2/authorize`, `/oauth2/token`, `/oauth2/jwks`, `/.well-known/openid-configuration`, `/userinfo`, etc.) |
| 2 | `authServerLoginFilterChain` | `/login`, `/css/**` | Custom login PAGE (GET) and form submission (POST). Has `formLogin()`. |
| 3 | `resourceFilterChain` | `/api/**` | Stateless API. Bearer JWT only. |
| 4 | `clientFilterChain` | (no `securityMatcher` — catches everything else) | Browser-facing app. Uses `oauth2Login()`. Includes URL-level RBAC. |

**Why this matters:** the previous broken attempts forgot Chain 2 entirely. Without it, the auth server redirects unauthenticated users to `/login`, the controller serves the login page, but the form POST has no filter to handle it — `formLogin()` is missing. Result: silent failure, login page appears to "not work."

---

## 6. Hardcoded users and OAuth2 clients

### Users (in-memory)

| Username | Password | Roles |
|---|---|---|
| `alice` | `password` | `ADMIN` |
| `bob` | `password` | `USER` |
| `carol` | `password` | `USER`, `ADMIN` |

Passwords stored as BCrypt hashes (using `BCryptPasswordEncoder` bean). The `carol` user with both roles is mandatory — she demonstrates that roles are additive.

### Registered OAuth2 clients (at the auth server)

Two clients, both using `authorization_code` grant:

```yaml
web-client:
  client-id: web-client
  client-secret: web-secret           # plain text via {noop} prefix
  redirect-uris:
    - http://localhost:8080/login/oauth2/code/web-client
  post-logout-redirect-uris:
    - http://localhost:8080/logout-page
  scopes: [openid, profile]
  token TTL: access=5m, refresh=30m

bruno-client:
  client-id: bruno-client
  client-secret: bruno-secret
  redirect-uris:
    - https://oauth.pstmn.io/v1/callback     # Postman default
    - http://localhost:9999/callback         # Bruno default (adjust if user has another)
  scopes: [openid, profile]
  token TTL: same
```

The short 5-minute access token TTL is intentional — it makes the expiry demo run quickly.

---

## 7. application.yml (full template — copy verbatim)

```yaml
server:
  port: 8080

# JTE config uses gg.jte prefix, NOT spring.jte. This is a common trap.
gg:
  jte:
    use-precompiled-templates: true
    development-mode: false

spring:
  application:
    name: jwt-rbac-demo

  security:
    oauth2:
      authorizationserver:
        client:
          web-client:
            registration:
              client-id: "web-client"
              client-secret: "{noop}web-secret"
              client-authentication-methods: ["client_secret_basic"]
              authorization-grant-types: ["authorization_code", "refresh_token"]
              redirect-uris: ["http://localhost:8080/login/oauth2/code/web-client"]
              post-logout-redirect-uris: ["http://localhost:8080/logout-page"]
              scopes: ["openid", "profile"]
            require-authorization-consent: false
            token:
              access-token-time-to-live: "5m"
              refresh-token-time-to-live: "30m"

          bruno-client:
            registration:
              client-id: "bruno-client"
              client-secret: "{noop}bruno-secret"
              client-authentication-methods: ["client_secret_basic"]
              authorization-grant-types: ["authorization_code", "refresh_token"]
              redirect-uris:
                - "https://oauth.pstmn.io/v1/callback"
                - "http://localhost:9999/callback"
              scopes: ["openid", "profile"]
            require-authorization-consent: false
            token:
              access-token-time-to-live: "5m"
              refresh-token-time-to-live: "30m"

      client:
        registration:
          web-client:
            provider: local-auth-server
            client-id: web-client
            client-secret: web-secret
            authorization-grant-type: authorization_code
            redirect-uri: "{baseUrl}/login/oauth2/code/{registrationId}"
            scope: [openid, profile]
        provider:
          local-auth-server:
            issuer-uri: http://localhost:8080

      resourceserver:
        jwt:
          issuer-uri: http://localhost:8080

logging:
  level:
    root: INFO
    com.example.jwtdemo: DEBUG
    org.springframework.security: INFO
    org.springframework.security.oauth2: INFO
  pattern:
    console: "%d{HH:mm:ss.SSS} %-5level [%logger{20}] %msg%n"
```

---

## 8. JTE templates (exact files)

Six templates in `src/main/jte/`. JTE syntax rules:
- Parameters declared at top: `@param Type name`
- For generic types, import first: `@import java.util.Set` then `@param Set<String> roles`
- Output: `${expression}`
- Conditional: `@if(condition) ... @endif`
- HTML-escaped by default (safe)

### login.jte
Params: `boolean error`, `boolean logout`. Renders a form posting to `/login` with username and password inputs. Shows the hardcoded users in a `<details>` block.

### home.jte
No params. Public landing page with a "Sign in" button linking to `/dashboard` (which triggers the OAuth2 flow due to the authentication requirement).

### logout.jte
No params. Post-logout landing page with a "Sign in again" button.

### dashboard.jte
Params: `String username`, `Set<String> roles`, `String accessToken`. Contains FOUR conditional sections:
1. Shared (always visible)
2. User-only (`@if(roles.contains("USER"))`)
3. Admin-only (`@if(roles.contains("ADMIN"))`)
4. User-or-Admin (`@if(roles.contains("USER") || roles.contains("ADMIN"))`)

Plus a textarea showing the raw access token so the user can copy it into Bruno / jwt.io. A logout form posting to `/logout`.

### admin.jte
Params: `String username`, `Set<String> roles`. Standalone admin-only page (URL-level RBAC blocks non-admins before this is reached).

### user.jte
Params: `String username`, `Set<String> roles`. Standalone user-only page.

---

## 9. Implementation specifics (the things that bite you)

### 9.1 Adding roles to the JWT

`TokenCustomizerConfig` registers an `OAuth2TokenCustomizer<JwtEncodingContext>` bean. It must add a `roles` claim to **both** the access token AND the ID token. Both are checked via:

```java
boolean isAccessToken = OAuth2TokenType.ACCESS_TOKEN.equals(context.getTokenType());
boolean isIdToken = "id_token".equals(context.getTokenType().getValue());
if (!isAccessToken && !isIdToken) return;
```

The claim value is a `Set<String>` of role names, stripped of the `ROLE_` prefix that Spring stores them with internally.

**Why both tokens:** the resource server reads roles from the access token, but the client app reads them from the ID token (via OidcUser). Forgetting the ID token means `hasRole("ADMIN")` never matches in the client and the dashboard sections never appear.

### 9.2 Client-side: mapping the roles claim to authorities

`ClientSecurityConfig` configures `oauth2Login()` with a `userAuthoritiesMapper`. This mapper:
- Iterates over the default authorities Spring assigns to the `OidcUser`
- For each `OidcUserAuthority`, reads `oidc.getIdToken().getClaims().get("roles")`
- For each role found, adds a `SimpleGrantedAuthority("ROLE_" + role)`

Without this mapper, the OidcUser only carries `SCOPE_*` authorities derived from scopes, and `hasRole("ADMIN")` never matches.

### 9.3 Resource-side: mapping the roles claim to authorities

`RoleClaimConverter implements Converter<Jwt, AbstractAuthenticationToken>`. It:
- Calls the default `JwtGrantedAuthoritiesConverter` to get `SCOPE_*` authorities
- Reads `jwt.getClaimAsStringList("roles")` and emits `ROLE_*` for each
- Returns a `JwtAuthenticationToken` with the combined set

Plugged into the resource server via `.oauth2ResourceServer(rs -> rs.jwt(jwt -> jwt.jwtAuthenticationConverter(new RoleClaimConverter())))`.

### 9.4 In-memory blocklist with proper interface

`TokenBlocklist` is a `@Service` exposing:
- `void add(String jti, long expiresAtMs)`
- `boolean contains(String jti)` — must auto-sweep expired entries
- `Map<String, Long> snapshot()` — for the debug endpoint

Implementation is `ConcurrentHashMap<String, Long>`. The interface is shaped so a Redis implementation (using `SETEX`) could be dropped in.

### 9.5 Hooking the blocklist into the JWT decoder

`ResourceSecurityConfig` provides a `JwtDecoder` bean built as:
- `NimbusJwtDecoder.withIssuerLocation(issuerUri).build()`
- Then a `DelegatingOAuth2TokenValidator<Jwt>` combining `JwtValidators.createDefaultWithIssuer(issuerUri)` AND `new BlocklistJwtValidator(blocklist)`
- Set via `decoder.setJwtValidator(combined)`

Without this, the blocklist is never consulted and revoked tokens still work.

### 9.6 Hooking the blocklist into logout

`ClientSecurityConfig` registers a `LogoutHandler` bean that:
- Casts the `Authentication` to `OAuth2AuthenticationToken`
- Looks up the `OAuth2AuthorizedClient` via `OAuth2AuthorizedClientService`
- Parses the access token JWT with `com.nimbusds.jwt.JWTParser`
- Extracts the `jti` claim
- Adds it to `TokenBlocklist` with the token's natural expiry time

Wired into the logout flow via `.logout(l -> l.addLogoutHandler(blocklistHandler))`.

### 9.7 CSRF disabling (with clear notes)

CSRF protection is disabled on the auth-server-login chain and the client chain. This is a deliberate learning shortcut so the login form POST and logout form POST work without adding CSRF token rendering everywhere. The README must call this out as something to fix in production.

CSRF is NOT disabled on the auth server protocol chain (it doesn't need to be — those endpoints have their own protection via client credentials).

### 9.8 OAuth2 authorization server settings

`AuthorizationServerSettings` bean must specify `issuer("http://localhost:8080")`. This must match the issuer-uri configured for both the OAuth2 client and the resource server.

### 9.9 RSA key generation

Generate a fresh 2048-bit RSA key pair at startup, expose via a `JWKSource<SecurityContext>` bean. Key pair lives in memory only — every restart invalidates all previously-issued tokens. The README must note this.

### 9.10 Method-level RBAC

`ClientSecurityConfig` is annotated `@EnableMethodSecurity`. Then `@PreAuthorize("hasRole('ADMIN')")` on `ApiController` methods provides defense-in-depth on top of URL-level rules.

---

## 10. Endpoints (must all work)

### Auth server (built-in via Spring Authorization Server)
- `GET /oauth2/authorize` — start OAuth2 flow
- `POST /oauth2/token` — exchange code for tokens
- `POST /oauth2/revoke` — revoke a token
- `POST /oauth2/introspect` — inspect a token
- `GET /oauth2/jwks` — public keys
- `GET /.well-known/openid-configuration` — discovery
- `GET /userinfo` — OIDC user info

### Auth server (custom)
- `GET /login` — serves `login.jte`
- `POST /login` — form submission, handled by Spring's `UsernamePasswordAuthenticationFilter`

### Client app (browser)
- `GET /` — public home (`home.jte`)
- `GET /dashboard` — any authenticated user (`dashboard.jte`)
- `GET /admin` — `ROLE_ADMIN` only (`admin.jte`)
- `GET /user` — `ROLE_USER` only (`user.jte`)
- `GET /logout-page` — public post-logout page (`logout.jte`)
- `POST /logout` — Spring's logout filter (custom blocklist handler)
- `GET /oauth2/authorization/web-client` — Spring's OAuth2 client login initiator
- `GET /login/oauth2/code/web-client` — Spring's OAuth2 client callback

### Resource server (API)
- `GET /api/whoami` — any authenticated JWT
- `GET /api/admin/stats` — `ROLE_ADMIN`
- `GET /api/user/profile` — `ROLE_USER`
- `GET /api/debug/blocklist` — `ROLE_ADMIN`, returns blocklist contents

---

## 11. Logging requirements

DEBUG level for `com.example.jwtdemo.*` throughout. Specific log statements that must exist:

- Startup banner with URL list and user list (printed once via `ApplicationReadyEvent`)
- `Building Authorization Server protocol filter chain (order=1)` — and equivalents for orders 2, 3, 4
- `Injecting roles into id_token for user='...': [...]`
- `Injecting roles into access_token for user='...': [...]`
- `Mapped JWT (sub='...', jti='...') to authorities: [...]`
- `Logout: blocklisted jti=... for user='...'`
- `REJECT token: jti=... is blocklisted (user logged out)`
- HTTP-level `GET /dashboard user='alice' roles=[ADMIN]`

These log lines are what the testing READMEs reference, so they must appear verbatim.

---

## 12. Documentation (must be produced)

Three Markdown files:

- **`README.md`** — overall project intro, tech stack, architecture diagram, how to run, hardcoded users, link to testing docs
- **`docs/TESTING-BROWSER.md`** — step-by-step browser walkthrough covering all RBAC scenarios + logout/blocklist demo
- **`docs/TESTING-API.md`** — Bruno/Postman walkthrough covering: (a) using Bruno's built-in OAuth2 helper for Authorization Code; (b) manually walking through the flow; (c) the blocklist demo across browser + Bruno

---

## 13. Verification protocol (DO NOT SKIP)

Before declaring the project complete, the AI tool MUST:

1. Run `mvn clean compile` and confirm it succeeds with zero errors
2. Run `mvn spring-boot:run` and confirm the startup banner appears
3. `curl http://localhost:8080/` returns HTML containing "JWT + RBAC Demo"
4. `curl http://localhost:8080/login` returns HTML containing "Sign in" and a form posting to `/login`
5. `curl http://localhost:8080/.well-known/openid-configuration` returns JSON containing `"issuer":"http://localhost:8080"`
6. `curl -i http://localhost:8080/dashboard` returns 302 redirect to `/oauth2/authorization/web-client`
7. `curl -i http://localhost:8080/api/whoami` returns 401

If any of these fail, fix the code — do NOT declare done.

**If the build environment has no internet access to Maven Central** (cannot download dependencies), the AI tool must say so explicitly rather than claim verification was performed.

---

## 14. Known pitfalls (from previous broken attempts)

These have all bitten the project at least once. Do not repeat them.

| Pitfall | Symptom | Fix |
|---|---|---|
| JTE templates placed in `src/main/resources/templates/` | Templates not found at runtime | They MUST be in `src/main/jte/`. JTE Maven plugin precompiles from there. |
| JTE properties under `spring.jte.*` | Config silently ignored | Use `gg.jte.*` prefix. |
| No JTE Maven plugin | Templates not packaged into JAR, runtime errors | Add `jte-maven-plugin`, phase `generate-sources`, goal `generate`. |
| Missing `formLogin()` chain | Login page renders, but POST returns 404 / silent failure | Add a SECOND filter chain for `/login` with `.formLogin().loginPage("/login").permitAll()`. |
| CSRF enabled with no token in form | Login form POST returns 403 | Either render CSRF token in `login.jte` OR disable CSRF on the login chain (preferred for this demo). |
| Roles only added to access token, not ID token | Client app's `hasRole("ADMIN")` never matches; dashboard sections never appear | Customize BOTH tokens in `TokenCustomizerConfig`. |
| Missing `userAuthoritiesMapper` on client | OidcUser has only SCOPE_* authorities | Add the mapper in `oauth2Login().userInfoEndpoint().userAuthoritiesMapper(...)`. |
| Spring Boot 4.x for this stack | Spring Authorization Server package relocation, unstable imports | Use Spring Boot 3.5.15 specifically. |
| `OAuth2AuthorizationServerConfigurer` import from `org.springframework.security.config...` | Wrong package | Correct package: `org.springframework.security.oauth2.server.authorization.config.annotation.web.configurers` |
| Resource server filter chain without `STATELESS` session policy | Sessions created on API requests | Set `sessionCreationPolicy(SessionCreationPolicy.STATELESS)`. |
| Token blocklist not registered as a `JwtDecoder` validator | Blocklisted tokens still work | Combine via `DelegatingOAuth2TokenValidator` and call `decoder.setJwtValidator(...)`. |

---

## 15. Output expectations

The AI tool should produce a complete project directory matching the layout in Section 4, ready to `cd` into and run `mvn spring-boot:run`. Templates in `src/main/jte/`, code in `src/main/java/`, config in `src/main/resources/`.

The tool should NOT:
- Add dependencies not listed in Section 3
- Use Lombok, Project Reactor, or any other "nice to have" libraries
- Use Gradle instead of Maven
- Use Thymeleaf instead of JTE
- Use a database instead of in-memory storage
- Skip the verification protocol in Section 13

The tool SHOULD:
- Add Javadoc to every configuration class explaining what it does and why
- Add Javadoc on key methods (`@Bean` methods, `LogoutHandler`, `Converter` implementations)
- Use clear logger names (one per class)
- Use `org.slf4j.Logger` and `org.slf4j.LoggerFactory` (NOT `java.util.logging`)
- Put comments explaining non-obvious decisions (e.g. why CSRF is disabled, why the blocklist is in-memory, why we customize both tokens)

---

## 16. Conversation script (if the AI tool prefers Q&A)

If the AI tool can't ingest this whole document at once, here's the conversation arc that produced the project originally. Each step locks in one design decision:

1. "I want to learn Spring Boot 3.5, Spring Security, OAuth2, JWT, RBAC for a server-rendered web app using JTE. Hardcoded data, no DB."
2. "Use Spring Authorization Server, Spring OAuth2 Client, Spring Resource Server. Authorization Code grant."
3. "One Spring Boot application, three packages: `authserver`, `client`, `resource`. Split deployable later."
4. "Use Bearer tokens internally, even though everything's in one process — easier to split later."
5. "RBAC at URL level, JTE section level, and `@PreAuthorize` method level."
6. "Custom JTE login page, not the default."
7. "Logout uses an in-memory blocklist of JWT `jti`. Designed to be Redis-swappable."
8. "Three hardcoded users: alice (ADMIN), bob (USER), carol (USER+ADMIN)."
9. "Two registered OAuth2 clients at the auth server: `web-client` for the browser and `bruno-client` for Bruno/Postman."
10. "Dashboard has four sections demonstrating each RBAC role pattern."
11. "Add good logging at DEBUG/INFO so each step of the flow is visible."
12. "Produce a `README.md`, a `docs/TESTING-BROWSER.md`, and a `docs/TESTING-API.md`."

Following this script in order, with the constraints in Sections 2 and 14 enforced throughout, should produce a working project on the first attempt.

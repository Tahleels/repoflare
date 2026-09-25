# Repolytic — System Design Engineering Reference

This file is a compact engineering checklist derived from the system-design topics used in the Hello Interview System Design in a Hurry material. Use it as a decision framework, not as a reason to add infrastructure without a real bottleneck.

## Primary reference

https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts

## Key technologies

https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies

## Decision rule

For every significant architecture choice:

1. Define the requirement.
2. Estimate scale/capacity where possible.
3. Identify the bottleneck.
4. Choose the simplest sufficient design.
5. State the trade-off.
6. State failure behavior.
7. Define what changes at larger scale.
8. Measure the result where practical.

Never add a distributed-systems technology simply to make the architecture look advanced.

---

# 1. System requirements

- Functional requirements
- Non-functional requirements
- Latency targets
- Throughput
- Availability
- Durability
- Consistency
- Security/privacy
- Scalability
- Cost/operational complexity

# 2. Capacity and bottleneck thinking

- Read/write workload
- Data size and growth
- Peak traffic
- Hot paths
- Storage limits
- CPU/memory/network limits
- Single-node limits
- Queue depth/backlog
- Identify the actual bottleneck before scaling.

# 3. Networking / service edge

- DNS
- API gateway
- Reverse proxy
- L4 load balancer
- L7 load balancer
- TLS termination
- Connection management
- Rate limiting
- Routing
- Health checks

Choose L4/L7 based on workload characteristics. Prefer stateless application servers where possible.

# 4. Caching

Use caching when it solves a demonstrated read/latency/computation bottleneck.

Consider:

- in-process cache
- Redis/distributed cache
- CDN cache
- client-side/HTTP cache
- cache-aside
- read-through
- write-through
- write-behind
- TTL
- LRU/LFU eviction
- cache invalidation
- cache stampede/thundering herd
- hot keys
- cache warming
- fallback behavior when cache is unavailable

Default pattern for many read-heavy workloads: cache-aside + TTL, with explicit invalidation/freshness reasoning.

# 5. Databases

### Relational

- PostgreSQL
- schema design
- normalization
- denormalization
- transactions
- indexes
- B-tree/hash/specialized indexes
- joins and their cost
- connection pooling
- query planning
- read replicas

### NoSQL

- key-value
- document
- column-family
- graph databases
- flexible schemas
- access-pattern-first modeling
- eventual vs strong consistency
- horizontal scaling

Do not choose SQL vs NoSQL using simplistic rules. Choose based on workload and required guarantees.

# 6. Partitioning and sharding

- Vertical partitioning
- Horizontal partitioning
- Database partitioning within one instance
- Sharding across machines
- shard key selection
- high cardinality
- even distribution
- hotspot avoidance
- cross-shard queries
- cross-shard transactions
- resharding
- rebalancing
- consistent hashing

Sharding must be justified by storage/throughput constraints. Treat it as a production-scale option unless the MVP genuinely requires it.

# 7. Replication and consistency

- primary/replica
- read replicas
- replication lag
- failover
- strong consistency
- eventual consistency
- stale reads
- conflict handling
- quorum-style reasoning where applicable

Document which consistency model each subsystem needs.

# 8. Queues and asynchronous systems

Use asynchronous work for operations that do not need to block a latency-sensitive request.

Know:

- queues
- streams
- partitions
- message ordering
- consumer groups
- retries
- exponential backoff
- dead-letter queues
- idempotency
- backpressure
- worker pools
- job status
- exactly-once vs at-least-once trade-offs

For Repolytic, long repository analysis/indexing/verification tasks are natural candidates for background work.

# 9. Reliability patterns

- timeout
- retry
- exponential backoff
- jitter
- idempotency
- circuit breaker
- bulkhead/isolation
- graceful degradation
- load shedding
- health checks
- failover
- dead-letter queues
- durable job state

Retries must be safe. Avoid retry storms.

# 10. Concurrency

- optimistic concurrency control
- pessimistic locking
- distributed locks
- queue-based serialization
- duplicate job suppression
- version checks
- atomic updates

For repository analysis, protect against concurrent indexing/change-analysis jobs operating on the same snapshot.

# 11. Storage and blob handling

For large artifacts, consider object storage such as S3-compatible storage.

Know:

- metadata vs blob separation
- presigned URLs where needed
- multipart/chunk uploads
- versioning
- lifecycle/retention
- encryption
- durability
- CDN integration

Do not use object storage as the primary relational metadata store.

# 12. Search

Repository intelligence can combine structured graph retrieval with text/code search.

Understand:

- exact search
- full-text search
- inverted indexes
- tokenization
- fuzzy search
- ranking
- semantic/vector retrieval where useful
- indexing lag
- search partitioning

For an MVP, PostgreSQL search or another simple proven option may be enough. Introduce a dedicated search engine only when justified.

# 13. CDN

Use a CDN when content benefits from geographically distributed edge caching, especially static assets or large public artifacts.

Understand:

- cache hit/miss
- TTL
- invalidation
- origin
- edge
- stale content

A CDN is not automatically useful for every API call or local developer workflow.

# 14. Rate limiting

Potential approaches:

- token bucket
- leaky bucket
- fixed/sliding windows
- distributed counters in Redis

Protect expensive operations such as AI calls and repository analysis jobs.

# 15. Distributed systems / scale

Understand:

- horizontal scaling
- stateless services
- service decomposition
- data locality
- partitioning
- sharding
- consistent hashing
- replication
- leader/follower patterns
- asynchronous processing
- eventual consistency
- failure domains

Only introduce distributed complexity when the requirements justify it.

# 16. Observability

Every production-worthy subsystem should expose:

- structured logs
- metrics
- traces
- request/job/analysis IDs
- latency distributions
- error rate
- queue depth
- cache hit rate
- database latency
- AI latency/token usage

For Repolytic, measure initial indexing, incremental update latency, graph traversal, retrieval, AI context preparation, and verification.

# 17. Security

- authentication
- authorization
- principle of least privilege
- secrets management
- encryption in transit
- encryption at rest
- secure subprocess execution
- input validation
- path traversal protection
- audit logs
- safe logging
- repository/source-code privacy

# 18. Data and API design

- clear contracts
- versioned APIs when necessary
- idempotent commands
- pagination for large result sets
- bounded queries
- timeouts
- consistent error model
- schema validation
- backward compatibility where relevant

# 19. Repolytic-specific data structures

Prefer efficient structures aligned with graph queries:

- node ID -> node metadata map
- node ID -> outgoing adjacency list
- node ID -> incoming adjacency/reverse dependency list
- relationship type indexes
- file path -> file/node lookup
- symbol qualified name -> symbol lookup
- content hash -> parsed snapshot cache
- repository snapshot -> change map
- change -> affected node set
- analysis cache key -> result

The graph must support incremental mutation without rebuilding unrelated components.

# 20. Repolytic architecture rule

The canonical workflow is:

```text
Initial scan
   -> structured repository index
   -> persistent graph

Later change
   -> diff detection
   -> changed symbols
   -> local re-analysis
   -> graph diff
   -> reverse dependency traversal
   -> affected subgraph
   -> targeted retrieval
   -> AI/Bob reasoning
   -> implementation
   -> post-change graph update
   -> targeted verification
```

The key optimization is:

> **Do structural work ahead of time and reuse it. Let AI reason over the relevant slice instead of rediscovering the whole repository.**

# 21. MVP vs production

### MVP

- one coherent backend/core
- local/shared graph engine
- PostgreSQL or similarly simple persistence
- Redis if valuable
- background worker if needed
- Docker
- VS Code extension
- CLI
- focused tests

### Production evolution

Potential later additions:

- API gateway
- L7/L4 load balancing
- multiple stateless API instances
- autoscaling workers
- distributed cache
- read replicas
- partitioning/sharding
- dedicated search engine
- object storage
- managed queue/stream
- multi-region/failover
- advanced observability
- stronger tenant isolation

The production diagram may contain these components, but they should be tied to concrete scaling/failure requirements.

# 22. Required engineering question

Before implementing any major feature, ask:

> What data structure, algorithm, persistence model, cache strategy, and system-design boundary make this feature correct, fast, reliable, and maintainable?

Then implement only what is justified.

# Subsystem Programming Model guide

[Please read the fundamentals first!](./fundamentals.md)

In Acacia, Subsystems are the vessel for modularising any and all Microkit code.

They are designed to allow you to express *client-server* relationships principally, but also
support *clientless* systems or *single-client* systems.

To leverage Acacia confidently and with minimal friction, it is important to understand the model
motivating the design of subsystems.

## Servers and clients

Our subsystem abstraction is principally oriented around *client-server* relationships because this
has turned out to be the most natural way to express many constructs when doing system design atop
the seL4 Microkit. For example, the [seL4 Device Driver Framework (sDDF)](https://github.com/au-ts/sddf)
and [LionsOS](https://github.com/au-ts/lionsos) both express their subsystems as some set of "server"
Protection domains, MRs, Maps, IRQs, etc. connected to some number of client Protection domains.

Client-server is generally a common pattern in the design of microkernel OSes for good reason ...
it is flexible and is good at capturing IPC and priority relationships between programs and the
(user-space) infrastructure they depend on.

### Servers

In Acacia, we consider a server to be a grouping of any number of:
* Protection Domains (or VMs), possibly with child Protection Domains,
* Memory Regions and mappings into ProtectionDomains,
* Channels,
* Configuration data,
* IRQs, IOPorts, IOMMU primitives (IOSpace/Maps), other Microkit objects,
* High level Python constructs or data used to compose the system.

The server has some notion of *clients*. By default, Acacia assumes clients are *ProtectionDomain*s (PDs).
The `Subsystem` object itself is a representation of the server and any logic needed to compose it.
* Subsystems have a default method `add_client()` which appends the client to an internal list `clients`.
* Subsystems may override `add_client()` to take arbitrary parameters or even make non-PD objects clients.
* If `add_client()` isn't needed it can be disabled at construction.

### Clients

Clients in Acacia are *ProtectionDomain*s. We assume the server offers some facility at the
granularity of a client PD.

E.g. for the sDDF network system:
* Clients connect to a TX virtualiser (sending packets),
* The RX virtualiser delivers packets to the client via a *copier* protection domain per-client,
* Memory regions and channels are used to define asynchronous, lock-free queues to connect the client to the virtualiser and copier respectively.

In this case, adding a client PD with `ethernet.add_client(pd, has_copier=True)` will add the client
to the ethernet subsystem's clients list and tell it to create a copier PD, then connect
the client to the TX virt + copier with queues.

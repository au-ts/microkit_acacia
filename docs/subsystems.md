<!--
    Copyright 2026, UNSW

    SPDX-License-Identifier: BSD-2-Clause
-->

# Subsystem Programming Model guide

[Please read the fundamentals first!](./fundamentals.md)

In Acacia, Subsystems are the vessel for modularising any and all Microkit code.

They are designed to allow you to express *client-server* relationships principally, but also
support *clientless* systems or *single-client* systems.

To leverage Acacia confidently and with minimal friction, it is important to understand the model
motivating the design of subsystems.

## Contents

**[Theoretical model of client-server Subsystems](#servers-and-clients)**

**[Walkthrough: making a simple client-free system](#basics-initialisation-and-config-structs)**
1. [Config Structs](#what-are-config-structs)
2. [Using your Subsystem in a metaprogram](#using-your-subsystem)
3. [Adding clients with build hooks](#adding-clients)
4. [Clients needing additional configuration](#adding-clients-with-extra-config)
5. [Subsystems that depend on other subsystems](#subsystems-depending-on-other-subsystems)

**[Acacia Build phase quick reference](#build-phases-quick-reference)**

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
* Subsystems define a **build hook** to create any Microkit elements needed to attach the clients to the server. E.g. channels, memory regions.

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

### Configuration data

To tell the compiled code everything that the infrastructure and client may need to know, we use [Config Structs](./configstructs.md).

Every `Subsystem` defines a method called `generate_config_structs` which returns a list of these, defining the config
to be patched into the server PDs as well as any clients, if needed.

## Designing a subsystem

Before writing your subsystem, consider the [Acacia Build process](./fundamentals.md#acacias-build-process).
It is very important to understand the order in which things are put together in order
to have your subsystem work nicely!

For your subsystem, there are [four critical stages you must consider](#build-phases-quick-reference).
1. Initialisation - run the `__init__()` of your subsystem. This happens at declaration time and is considered a part of the metaprogram.
2. Assembly phase - the metaprogram has finished running and you can assume that all clients are added, all manual allocation of vaddrs and IDs have completed, and any other subsystems we depend on exist.
3. Allocation phase - if you needed to create physical memory regions without assigning them an address, they are allocated after the assembly phase. This is done automatically by `acacia.System`.
4. Final phase - everything is frozen, config structs and XML can now be generated.


### Basics: initialisation and config structs
In order to explain these, let's define a super simple system.
To make a subsystem, you must create a subclass of `acacia.Subsystem`. You must
initialise the super class with `super().__init__()` by supplying the Acacia `System` instance that will be used and a name.

Subsystems are similar to the [Microkit primitives](./fundamentals.md#microkit-primitives) in that they cannot exist without a parent `System`,
since the `System` represents what will be in the Microkit XML file.


In practically all subsystems, you will define a minimum of the constructor and a config struct method.

In this case, our subsystem has a simple task:
* Create some ProtectionDomain called `secret_server`, assuming we have some C code that compiled to `secret_server.elf`.
* Take some secret number from the metaprogram and patch it into the secret server.


```python
class YourSubsystem(Subsystem):
    def __init__(self, sdf: System, secret_number: int):
        super().__init__(sdf, "Your Subsystem Name!", clients_allowed=True)

        self.secret = secret_number
        self.server_pd = ProtectionDomain(sdf, "your_server", "your_server.elf")
        ...

    def generate_config_structs(self) -> List[ConfigStruct]:
        return [
            ConfigStruct(
            {
                "secret_number" : self.secret
            },
            target_file = self.server_pd.prog_image,
            section_name = "server_config"
            type_name = "secretServerConfig_t"
            )
        ]
```

We have no clients yet, but our sole PD acts as an isolated server. We will add client support in [Adding Clients](#adding-clients).


#### Defining your server infrastructure

The infrastructure is effectively "everything that is not a client or something used to connect the client to the infrastructure".

You should always create as many of your infrastructure Microkit elements  as possible in `__init__()`. There are a few reasons for this:
* It keeps things simple, don't defer work if you don't need to.
* It allows more flexibility - anything you create at `__init__()` can be directly manipulated in the metaprogram. This is handy for experimentation, e.g. changing priorities.
* It makes it easy to add parts of your infrastructure as clients to other servers (more in server-server dependencies section below).

In some cases, it is not possible to make everything right away. The infrastructure might depend on your clients somehow, and you cannot know these at `__init__`.
You should use a *build hook* to manage such cases. We will discuss this once we introduce clients in [Adding Clients](#adding-clients).



#### What are config structs?
**Config struct?** ... this is our mechanism for patching data into compiled programs. See [Config Structs guide](./configstructs.md).

Our secret server only needs one right now - a way to specify the secret number we pass in at `__init__()`.

In this case, imagine that there is a corresponding C structure:
```c
typedef struct secretServerConfig {
    uint32_t secret_number;
}
```

... and this is defined as a **section** in `secret_server.c`
```c
__attribute__((__section__(".secret_config"))) secretServerConfig_t config;
```
Acacia will patch the data we define in `ConfigStruct` into this section, which can be accessed like a normal variable.
```c
printf("The secret number is %u\n", config.secret_number);
```

All you need to do in Acacia is to specify the mapping between **names of fields** and **their Python values** and the type, section and file name to target it. The Python values which will be translated into C types. Not all Python types can be converted, see [Serialisable Types](./configstructs.md#types).

```python
    def generate_config_structs(self) -> List[ConfigStruct]:
        return [
            ConfigStruct(
            # Define struct field name -> python val map
            {
                "secret_number" : self.secret
            },
            # Which compiled ELF file do we patch?
            target_file = self.server_pd.prog_image,
            # Which section in the ELF?
            section_name = "server_config",
            # What is the name of the struct type, for sanity checking?
            type_name = "secretServerConfig_t"
        )
    ]
...
```

#### Using your subsystem

Once you have written your implementation (and any corresponding C/Rust/Pancake code + supporting Makefiles),
you can express a **metaprogram** to build the system.

meta.py
```python
sdf = System(aarch64, paddr_top=0x90000000, DeviceTreeBlob(""./board.dts"))
MySubsystem(sdf, 42)
sdf.make_config_struct("./build")           # Outputs config struct blobs to `./build`
sdf.write_xml_file("secret_server.system")  # Write Microkit XML file
```

In this case, we are setting `secretServerConfig_t.secret_number` to `uint32_t` 42. Running `secret_server.system` through Microkit and then executing the binary we see:
```
The secret number is 42
```

### Adding clients

So we can now create simple infrastructure and configuration data. Let's extend our secret server
to have **clients** ... each client will be connected with a Microkit Channel and can perform a
protected procedure call to get the secret data.

We cannot do anything about our clients in `__init__()` since none will have been added yet, so
we must instead utilise the pre-defined method `add_client(self, client_pd: ProtectionDomain)`.
This method is defined by `Subsystem()` and will simply add the PD to a list in the superclass called `clients`.

(Note: if the subsystem is initialised with `allow_clients=False` this method will be disabled.)

Instead, we must use a **build hook** ... a method that is run at the [assembly phase](#assembly-phase).

#### Build hooks

Build hooked methods are annotated with a special decorator to tell Acacia to run them at the [assembly phase](#assembly-phase). You can have as many as you want, and Acacia will execute them top-to-bottom within a class. I.e. the one closest to the top of the file will run first. We can add a build hook to connect our clients.

```python
class YourSubsystem(Subsystem):
    def __init__(self, sdf: System, secret_number: int):
        self.client_channels: Dict[ProtectionDomain, int]   # Keep a list of IDs for clients
        ...

    @build_hook
    def connect_clients(self):
        for c in self.clients:
            ch = Channel(
                self.sdf,
                Channel.End(c, can_notify=False, can_pp=True),
                Channel.End(self.secret_server),
            )
            # Store channel ID so client knows who to call
            self.client_channels[c] = ch.id_for_pd(c)
```

As you can see, we make a new `connect_clients()` method which is annotated as a build hook.
It will now be run automatically once the [assembly phase](#assembly-phase) runs and Acacia begins to build this subsystem instance.

We create a channel from every client to the secret server, and we then store
the numerical ID of the channel (i.e. what the client will `microkit_ppcall()`) in a dictionary.

#### Config structs for clients

We've got an ID for each client, now we must get it to them! We can extend our `generate_config_structs` to make more config structs for the clients.
```python
    def generate_config_structs(self) -> List[ConfigStruct]:
        return [
            ConfigStruct(
            {
                "secret_number" : self.secret
            },
            target_file = self.server_pd.prog_image,
            section_name = "server_config"
            type_name = "secretServerConfig_t"
            )
        ] + [
            ConfigStruct(
                {
                    secret_ch : self.client_channels[c]
                },
                target_file = c.prog_image,
                section_name = "secret_ch",
                type_name = "secretClientConfig_t"
            )
            for c in self.clients
        ]
```

We do not need to worry about if the clients are connected, since Acacia will only
ever call `generate_config_structs` after the assembly phase finishes.

### Adding clients with extra config

If you need to have additional configuration data alongside your clients, you can
**override the `add_client()` method**.

I.e. in your subsystem, define `add_client()`, making sure to still `super()` call the original method (unless you are sure you don't need it).
```python
def add_client(self, client: ProtectionDomain, client_needs_thing: bool):
    super().add_client(client)  # Add to clients list
    self.client_configs[client] = client_needs_thing
   ...

@build_hook
def connect_clients(self):
    for c in self.clients:
        ...

        # Check config here
        if self.client_configs[c]:
            ...

```

**In most cases...** you should do nothing other than keep a reference to the client config in the initialisation phase. Create all Microkit objects etc. in a build hook, not in `add_client()`. This is because...
* The PD might not be in a final state yet, i.e. the user might modify it in the metaprogram still.
* Other subsystems may also have it as a client and may need to run before us.
* It's much less confusing to isolate all connection logic to a build hook.

**For an example**, see the sDDF `net.py` class which overloads the method to add
options for MAC addresses and turning the copier on or off.

#### Sidenote: build hooks and OO programming

Build hooks support inheritance and multiple inheritance. In these cases, they will run
in [Method Resolution Order](https://docs.python.org/3/howto/mro.html), that is,
in the same order as Python would precedence of methods.

* If a parent class defines build hooks, they will always run before the child class's build hooks do.
* If a child overrides a parent's build hook, it will run in the same order as any other build hook defined in the child.
* If a child class overrides a parent's build hook and **doesn't annotate it as one** (i.e. no `@build_hook`), it will not run.

We recommend minimising inheritance with build hooks. We only support MRO in order to make it sane to use this where it might be unavoidable.

### Subsystems depending on other subsystems

It is very possible that your subsystem (or some infrastructure inside of it) may need
to use the facilities of another subsystem.

For example, let's imagine that our secret server needs a security feature ... it wants to use the sDDF timer driver to limit how often clients can check the secret.

In this case, we most follow **one very important rule**:
> Always capture Subsystem dependencies and add infrastructure as clients in `__init__()`!

I.e.
```python
class YourSubsystem(Subsystem):
    def __init__(self, sdf: System, secret_number: int, timer: sDDFTimer):
        super().__init__(sdf, "Your Subsystem Name!", clients_allowed=True)

        self.secret = secret_number
        self.client_channels: Dict[ProtectionDomain, int]   # Keep a list of IDs for clients
        self.server_pd = ProtectionDomain(sdf, "your_server", "your_server.elf")

        # Add the server as a client of the timer.
        timer.add_client(self.server_pd)
        ...
```

Acacia will [always run the build hooks of
Subsystems in the order they are declared](#assembly-phase). We have a tension here...
* We want to take a reference to the other subsystem right away, to ensure the we have our dependency, but,
* Our dependent subsystem will build before us, so we cannot safely add ourselves as a client in the assembly phase.

We will implement a dependency graph to order building of subsystems in the
assembly phase in the future.

## Build phases quick reference.

### Initialisation phase

**When?**
Your `__init__()` of your Subsystem, any time before Acacia begins [assembly](#assembly-phase). Conceptually, "in the metaprogram".

**What to do?**
Set up all infrastructure that doesn't need to know about clients

**Constraints**
Clients are still unknown.

### Assembly phase

**When?**
As soon as the metaprogram calls a **terminal action** ... i.e. trying to generate config structs
or write the XML. This triggers Acacia to begin assembly.

Subsystems are assembled in the order they are declared, i.e.
```python
FirstSubsystem(sdf)
SecondSubsystem(sdf)
ThirdSubsystem(sdf)
...
sdf.write_xml()
```
... will run the build hooks for the three subsystems in top-to-bottom order (first, second, third).

**What to do?**
Create connections between clients and infrastructure, modify infrastructure that depends on clients,
interact with other subsystems.

**Constraints**
Manual allocation of map virtual addresses and manual allocation of IDs for IRQs, IOPorts, child PDs is disabled.

This is to prevent collisions between multiple Subsystems who target the same client ... two subsystems cannot
both demand their map has a vaddr of 0x20202020 since this would overlap.

### Allocation phase

**When?**
As soon as all Subsystems are assembled.

**What to do?**
Nothing, Acacia will allocate any outstanding physical memory addresses that are not allocated yet.

**Constraints**
Nothinig should run now.

### Final phase

**When?**
As soon as allocation completes.

**What to do?**
Tell Acacia to emit XML or config structs to your build directory.

**Constraints**
Subsystems can no longer have clients added. Microkit primitives can no longer be instantiated.

## Things to avoid

If you run into any of the following, it probably means something has gone wrong in your design!


| Problem | Reason |
| :--- | :--- |
| Attempting to access clients in `__init__` | Clients should only be added after init! |
| Hardcoding virtual addresses or IDs in a subsystem| Automatic mappings are generally better as hard coded ones will clash. Automatic allocation and config structs mean that it is not necessary except for physicall addresses in drivers. |
| Creating new Microkit elements in `generate_config_structs`| All Microkit elements are expected to exist before getting here. Acacia will attempt to crash if you allocate too late. Use build hooks instead.|
| Lots of build hooks | Confusing, and usually not needed. Build hooks run in top-to-bottom order of declaration |

<!--
    Copyright 2026, UNSW

    SPDX-License-Identifier: BSD-2-Clause
-->

# Fundamentals of Acacia

This page describes the fundamental ideas behind Acacia and how to use it.

Before attempting to use Acacia, you **must understand the basics of using the seL4 Microkit!**
Please complete the [seL4 Microkit Tutorial](https://docs.sel4.systems/projects/microkit/tutorial/welcome.html) if you haven't already.
This will teach you the basics of how to compose a system with these objects.

## Why do we need another tool?

The seL4 Microkit is designed to make using seL4 accessible and easy. It does this! It does not
include any easy way to modularise and reuse parts of Microkit systems however, and this is
generally problematic given that each module in the system must be connected by a set of Microkit
objects.

Consider a naïve case ... you have made an application on top of the Microkit that acts as a server.

* It has some number of clients, each connected with a notification and a shared memory mapping.
* Each client must know the channel ID for notifications and the vaddr of the shared memory mapping.

If you wanted to use this in a new project, you would have little choice but to manually add
the channels and mappings to the XML, and come up with your own way to get the vaddrs and channel IDs
to the clients (via C preprocessor or similar).

This is simply no good! We need a way to express modules in Microkit.

## What makes a module?

Modules consist of:
* Some (compiled) source code,
* A set of Microkit elements implementing internal parts of your module,
* A set of Microkit elements connecting the module to other parts of the target system,
* Some configuration data to tell business logic about these Microkit elements. (e.g. "what is the channel ID of this channel")
* (possibly) other system-specific configuration such as sDDF driver configurations or device tree info.

Acacia offers a *Subsystem* abstraction that supports all of the above except for compilation of source code (currently).

Every metaprogram must contain at least one *System*, a representation of the entire OS image we are building. This contains
all [Microkit Primitives](#microkit-primitives) and all *Subsystem*s we will use. **You can think of
the `System` as a high-level representation of the Microkit XML file.**

**To learn how to write subsystems, please start by reading [the Subsystem Programming model guide](./subsystems.md).** This is very important, as there are some potential foot-guns in this process. We have made an effort to minimise them and keep the process as simple as possible however.

## Acacia's build process

Acacia has several distinct stages, starting with system specification (executing metaprogram) and ending with a terminal action (generating Microkit XML
or config structs).

0. Declarative file (YAML) executed if present (NOT YET IMPLEMENTED).
1. Metaprogram begins to execute. (If a declarative file was executed, the metaprogram receives a handle to the `System` and `DeviceTreeBlob` created so far).
  1. Device tree blob is loaded
  2. `System` created, defining board-specific details such as the top of physical memory.
  3. All subsystems and any desired Microkit primitives in the metaprogram are initialised.
2. A **terminal action** is called. This will trigger Acacia to build the system and indicates that the user is finished modifying things.
3. Acacia assembles the system

    1. All subsystems are constructed - i.e. their `build` method is invoked. All of their build-time methods (annotated with `@build_hook`) are executed.
    2. Acacia allocates all undefined fields in Microkit primitives. Currently, this only includes physical addresses of MRs that are not assigned yet. In the future we may add support to do this for channel IDs and virtual addresses, but these are not strictly required to express modules.

    **Note**: the order in which subsystems are constructed is important. Acacia's imperative Python interface encourages expressing dependencies in an

4. If requested, all config structs are generated automatically by calling `Subsystem.generate_config_structs()` for each subsystem. In the metaprogram, this happens when calling `create_config_struct`.

### Terminal actions

Terminal actions refer to calls to Acacia's Python interface (in metaprograms or other tooling) which cause Acacia to assemble the system.
 calling EITHER `create_config_structs` or `generate_xml` has the same effect, and calling both
      will never cause a repeated build of the system. You can use both, or just one.


## Using Acacia

Acacia is invoked using a `metaprogram` - a Python script that imports any needed Acacia modules, interacts with your build system
and specifies the system architecture. In order to make a useful system, you likely will need to use the [seL4 Device Driver Framework (sDDF)](https://github.com/au-ts/sddf)
to access key drivers like serial and networking. The sDDF examples directory shows many metaprograms of varying complexity and are a good reference.

We are working on two things to improve the ergonomics of Acacia currently:
1. An Acacia executable `python -m acacia`. This will allow you to invoke metaprograms without boilerplate like passing in device tree blobs.
2. An Acacia declarative YAML interface, enabling structural descriptions of projects without needing a metaprogram. These will be loaded using the Acacia executable.
3. Mixed usage of metaprograms and declarative files, where the declarative file runs first and hands off the current system architecture to the metaprogram for further changes.

Irrespective of your method to use Acacia, the fundamental tools are the same.

## API documentation

We have used extensive in-code documentation for all APIs. We are deploying a docsite using a generator
in the near future to leverage this. In the mean time, you can use `pydoc` to browse.

E.g.
```
python -m pydoc acacia.Subsystem
```

We have included docs of a more "philosophical" nature in this directory, and these will also be
rendered in the docsite once it is created.

## Acacia's tooling

### Microkit Primitives

Acacia has direct representations of all seL4 Microkit objects, allowing you to programmatically create anything that can be represented in a Microkit XML file.

I.e.
* [Protection Domains](https://docs.sel4.systems/projects/microkit/manual/latest/#pd) representing executing programs with a VSpace, CSpace and scheduling context.
* [Virtual Machines](https://docs.sel4.systems/projects/microkit/manual/latest/#vm) are containers for running guest OSes under the Microkit, behaving similarly to PDs.
* [Memory Regions](https://docs.sel4.systems/projects/microkit/manual/latest/#mr) representing ranges of memory.
* [Channels](https://docs.sel4.systems/projects/microkit/manual/latest/#channels) are IPC connections enabling [PPCs](https://docs.sel4.systems/projects/microkit/manual/latest/#pp) and [Notifications](https://docs.sel4.systems/projects/microkit/manual/latest/#notification).
* [Interrupts](https://docs.sel4.systems/projects/microkit/manual/latest/#irq) representing mappings of hardware IRQs to PDs.
* [IOPorts](https://docs.sel4.systems/projects/microkit/manual/latest/#ioport) for x86 IOPort mappings.
* [IO Address spaces and mappings](https://docs.sel4.systems/projects/microkit/manual/latest/#io_address_space) for IOMMU interaction.


### Device tree parsing

Acacia has a [Device Tree Parser](./devicetree.md) to help you extract pertinent information from the device tree for your work.
This is principally useful for writing drivers and configuring the system based on the target board on RISCV and ARM platforms.

In most cases, you will not need to directly interact with the device tree parser. If you are using the sDDF, it is able
to handle all device tree interactions for you for all included drivers.

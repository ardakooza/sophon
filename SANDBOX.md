# Sophon Agent Sandbox

**Durum:** Linux process/filesystem/network sandbox implemented for Agent provider requests.

## 1. Activation

In XAF:

```xaf
agent {
    id = 1001
    name = "Research Agent"
    policy = 2001
    permission { execute = true }
    security { container = true }
    connection {
        provider = "openrouter"
        model = "provider/model-id"
        key = "OPENROUTER_API_KEY"
    }
}

policy {
    id = 2001
    access { agent }
    action { read = true }
}
```

When `security.container = true`, the Agent provider request is executed in a separate sandbox process. If the host cannot establish the required isolation, Sophon raises `A035`; it never retries the request in the parent process without isolation.

## 2. Isolation boundaries

The Linux backend creates user, mount, PID, UTS, IPC and network namespaces, then enters a `chroot` containing:

- the system Python runtime and its required shared libraries;
- CA certificates and DNS/hosts configuration;
- a read-only bind mount of the active Sophon project;
- a temporary isolated `/tmp` and one Unix-domain proxy socket.

The sandbox process receives resource limits for CPU time, address space, file size, open descriptors, process count and core dumps. `no_new_privs` is enabled. The process starts as PID 1 in its PID namespace.

The host filesystem is not generally mounted into the sandbox. In particular, host `/etc/passwd` is not visible. The active project is mounted read-only, so Agent input files and `AGENT.md` can be read but cannot be changed by the sandbox worker.

## 3. Network policy

The sandbox has its own network namespace with no external network interface. The only egress path is a host-side Unix-socket CONNECT proxy. That proxy accepts only `openrouter.ai:443`; other destinations are rejected. TLS is established by the sandbox worker to OpenRouter through the tunnel, so certificate verification remains enabled in the worker.

The host proxy itself performs the outbound TCP connection. The sandbox worker cannot directly open arbitrary internet or LAN connections.

## 4. Scope and current limitations

This sandbox currently isolates the local Sophon Agent provider-request process. It does not yet execute model-generated code or provide Agent tool execution; those are not implemented in the Agent runtime yet. `execute.file` remains the separately policy-controlled Sophon subprogram mechanism.

The backend is Linux-specific and requires `unshare` with user, mount, PID, UTS, IPC and network namespaces, working mount/chroot permissions, and `/usr/bin/python3`. Android/Termux and proot environments may not expose these kernel capabilities. In that case container mode fails closed with `A035`.

This is a namespace/chroot sandbox, not a Docker container or virtual machine. It currently uses process resource limits and `no_new_privs`; dedicated seccomp profiles, cgroup quotas and per-Agent writable workspaces are future hardening work.

## 5. Verification

The integration suite enters the real namespace/chroot and verifies:

- PID namespace process ID is 1;
- sandbox root is `/` and working directory is `/workspace`;
- host `/etc/passwd` is not visible;
- the project mount is read-only;
- direct external network access is blocked;
- container-mode Agent input validation returns its Sophon diagnostic from inside the sandbox, without an unsandboxed fallback.

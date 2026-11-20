"""Native per-session permissions for the pinned rc.5 Orchestrator build."""

from hashlib import sha256
from pathlib import Path


GATEWAY_BEFORE = "    async sessionModels(sessionId, signal) {"
GATEWAY_AFTER = """    async nativePermission(sessionId, signal) {
        const projection = await this.wire.call("session/projections", { request: { sessionId } }, z.object({
            values: z.object({ permissions: z.object({
                currentValue: z.enum(["read-only", "workspace-write", "danger-full-access"]),
            }) }),
        }), signal);
        return projection.value.values.permissions.currentValue;
    }
    async selectNativePermission(sessionId, permission) {
        if (!["read-only", "workspace-write", "danger-full-access"].includes(permission))
            throw new Error("Unknown Harness permission preset");
        if (await this.nativePermission(sessionId) !== permission) {
            const receipt = await this.wire.call("commands/execute", {
                agentId: sessionId, line: "/permission " + permission, submittedAttachments: [],
            }, z.object({ result: z.object({ kind: z.literal("success") }) }));
            if (receipt.value.result.kind !== "success" || await this.nativePermission(sessionId) !== permission)
                throw new Error("Harness did not activate the requested permission");
        }
    }
    async sessionModels(sessionId, signal) {"""

MCP_SCHEMA_BEFORE = """            workspaceMode: z
                .enum(["read-only", "exclusive-write"])
                .default("exclusive-write")
                .describe("Bridge-local cooperative workspace claim only; it is not a DSH Host filesystem sandbox selector or verifier."),
            modelProfile: z
                .enum(modelProfiles)
                .optional()
                .describe("Semantic route: flash/pro use deepseek-official;"""
MCP_SCHEMA_AFTER = """            workspaceMode: z
                .enum(["read-only", "exclusive-write"])
                .optional()
                .describe("Bridge-local cooperative workspace claim. Pass exclusive-write explicitly when selecting a native write permission."),
            permissionMode: z.enum(["read-only", "workspace-write", "danger-full-access"]).optional()
                .describe("Native Harness permission for this new session. Defaults to read-only. For write access, pass workspaceMode=exclusive-write. Use danger-full-access only for a task the user explicitly authorized to run without a filesystem sandbox."),
            modelProfile: z
                .enum(modelProfiles)
                .optional()
                .describe("Semantic route: flash/pro use deepseek-official;"""
MCP_ARGS_BEFORE = "title, waitSeconds, workspaceMode, modelProfile, reasoningEffort, selectionReason, visualIntent, complexity }) => handled(() => service.delegate({"
MCP_ARGS_AFTER = MCP_ARGS_BEFORE.replace("workspaceMode, modelProfile", "workspaceMode, permissionMode, modelProfile")
MCP_CALL_BEFORE = """        workspaceMode,
        ...(agentPreset === undefined ? {} : { agentPreset }),"""
MCP_CALL_AFTER = """        workspaceMode,
        ...(permissionMode === undefined ? {} : { permissionMode }),
        ...(agentPreset === undefined ? {} : { agentPreset }),"""

SERVICE_SETUP_BEFORE = """        const agentPreset = input.agentPreset?.trim() || this.config.defaultAgentPreset;
        const created = await this.api.sessionCreate"""
SERVICE_SETUP_AFTER = """        const permissionMode = input.permissionMode ?? "read-only";
        if (permissionMode !== "read-only" && input.workspaceMode !== "exclusive-write")
            throw new Error("Native write permissions require the exclusive-write workspace claim");
        if (typeof this.api.selectNativePermission !== "function")
            throw new Error("Verified native permissions require the official Harness Gateway");
        const agentPreset = input.agentPreset?.trim() || this.config.defaultAgentPreset;
        const created = await this.api.sessionCreate"""
SERVICE_SELECT_BEFORE = """        const beforePrompt = await this.ledger.snapshot(task.taskId);
        let models;"""
SERVICE_SELECT_AFTER = """        try {
            await this.api.selectNativePermission(created.sessionId, permissionMode);
        }
        catch (error) {
            await this.claims.release(task.taskId).catch(() => undefined);
            throw new DelegationSetupError("permission", "Harness did not verify the requested native permission; no prompt was sent", created.sessionId, task.taskId, { cause: error });
        }
        (this.nativeSessionPermissions ??= new Map()).set(created.sessionId, permissionMode);
        const beforePrompt = await this.ledger.snapshot(task.taskId);
        let models;"""
SERVICE_RESULT_BEFORE = """            workspaceClaim,
            workspaceClaimSemantics: workspaceClaimSemantics(),
            ...(promptTrackingWarning"""
SERVICE_RESULT_AFTER = """            workspaceClaim,
            permissionMode,
            workspaceClaimSemantics: workspaceClaimSemantics(),
            ...(promptTrackingWarning"""
SERVICE_RESUME_BEFORE = """        const { task } = view;
        let models;"""
SERVICE_RESUME_AFTER = """        const { task } = view;
        const expectedPermission = this.nativeSessionPermissions?.get(task.sessionId) ?? "read-only";
        const activePermission = await this.api.nativePermission(task.sessionId);
        if (activePermission !== expectedPermission)
            throw new Error("Native permission changed or could not be recovered; create a new task with the desired permission");
        let models;"""

PATCHES = {
    "gateway-dsh-client.js": (
        "87a58200e1d226de8d378ec683da82e0e70a40bd84ae38b130fd31c54220ec28",
        [(GATEWAY_BEFORE, GATEWAY_AFTER)],
    ),
    "mcp-server.js": (
        "f2ae9400219c4da991df1c158653c77da4f0b1f2d0248cdebc7facf2ca9e1fcb",
        [(MCP_SCHEMA_BEFORE, MCP_SCHEMA_AFTER), (MCP_ARGS_BEFORE, MCP_ARGS_AFTER), (MCP_CALL_BEFORE, MCP_CALL_AFTER)],
    ),
    "bridge-service.js": (
        "c7529643ed0c7e58685408646935cbcdb0dd03ddee52d4d4509b4f8e549c780d",
        [
            (SERVICE_SETUP_BEFORE, SERVICE_SETUP_AFTER),
            (SERVICE_SELECT_BEFORE, SERVICE_SELECT_AFTER),
            (SERVICE_RESULT_BEFORE, SERVICE_RESULT_AFTER),
            (SERVICE_RESUME_BEFORE, SERVICE_RESUME_AFTER),
        ],
    ),
}


def permission_route(path, data):
    expected, changes = PATCHES[Path(path).name]
    base = data.replace(b"\r\n", b"\n")
    for original, updated in changes:
        base = base.replace(updated.encode(), original.encode(), 1)
    if sha256(base).hexdigest() != expected:
        raise ValueError(f"{Path(path).name} is not the pinned Orchestrator build. It was kept.")
    for original, updated in changes:
        if base.count(original.encode()) != 1:
            raise ValueError(f"Could not locate the permission patch point in {Path(path).name}.")
        base = base.replace(original.encode(), updated.encode(), 1)
    return base

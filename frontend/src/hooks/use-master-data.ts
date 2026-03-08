import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  depotApi,
  vehicleApi,
  vehicleTemplateApi,
  routeApi,
  stopApi,
  permissionApi,
} from "@/api";
import type {
  CreateDepotRequest,
  UpdateDepotRequest,
  CreateVehicleRequest,
  CreateVehicleBatchRequest,
  DuplicateVehicleBatchRequest,
  UpdateVehicleRequest,
  CreateVehicleTemplateRequest,
  UpdateVehicleTemplateRequest,
  CreateRouteRequest,
  UpdateRouteRequest,
  ImportOdptRoutesRequest,
  ImportGtfsRoutesRequest,
  ImportOdptStopsRequest,
  ImportGtfsStopsRequest,
  UpdateDepotRoutePermissionsRequest,
  UpdateVehicleRoutePermissionsRequest,
} from "@/types";
import { scenarioKeys } from "./use-scenario";

// ── Query keys ────────────────────────────────────────────────

export const depotKeys = {
  all: (scenarioId: string) => ["depots", scenarioId] as const,
  detail: (scenarioId: string, depotId: string) =>
    ["depots", scenarioId, depotId] as const,
};

export const vehicleKeys = {
  all: (scenarioId: string) => ["vehicles", scenarioId] as const,
  byDepot: (scenarioId: string, depotId: string) =>
    ["vehicles", scenarioId, { depotId }] as const,
  detail: (scenarioId: string, vehicleId: string) =>
    ["vehicles", scenarioId, vehicleId] as const,
  templates: (scenarioId: string) => ["vehicle-templates", scenarioId] as const,
  templateDetail: (scenarioId: string, templateId: string) =>
    ["vehicle-templates", scenarioId, templateId] as const,
};

export const routeKeys = {
  all: (scenarioId: string) => ["routes", scenarioId] as const,
  filtered: (
    scenarioId: string,
    filters: { depotId?: string; operator?: string; groupByFamily?: boolean },
  ) => ["routes", scenarioId, filters] as const,
  detail: (scenarioId: string, routeId: string) =>
    ["routes", scenarioId, routeId] as const,
};

export const stopKeys = {
  all: (scenarioId: string) => ["stops", scenarioId] as const,
};

export const permissionKeys = {
  depotRoute: (scenarioId: string) =>
    ["permissions", scenarioId, "depot-route"] as const,
  vehicleRoute: (scenarioId: string) =>
    ["permissions", scenarioId, "vehicle-route"] as const,
};

function invalidateDispatchOutputs(qc: ReturnType<typeof useQueryClient>, scenarioId: string) {
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "trips"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "graph"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "blocks"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "duties"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "dispatch-plan"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "simulation"], exact: false });
  qc.invalidateQueries({ queryKey: ["scenarios", scenarioId, "optimization"], exact: false });
  qc.invalidateQueries({ queryKey: scenarioKeys.detail(scenarioId) });
}

// ── Depot queries ─────────────────────────────────────────────

export function useDepots(scenarioId: string) {
  return useQuery({
    queryKey: depotKeys.all(scenarioId),
    queryFn: () => depotApi.list(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useDepot(scenarioId: string, depotId: string) {
  return useQuery({
    queryKey: depotKeys.detail(scenarioId, depotId),
    queryFn: () => depotApi.get(scenarioId, depotId),
    enabled: !!scenarioId && !!depotId,
  });
}

export function useCreateDepot(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDepotRequest) =>
      depotApi.create(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: depotKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useUpdateDepot(scenarioId: string, depotId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateDepotRequest) =>
      depotApi.update(scenarioId, depotId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: depotKeys.detail(scenarioId, depotId) });
      qc.invalidateQueries({ queryKey: depotKeys.all(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useDeleteDepot(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (depotId: string) => depotApi.delete(scenarioId, depotId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: depotKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

// ── Vehicle queries ───────────────────────────────────────────

export function useVehicles(scenarioId: string, depotId?: string) {
  return useQuery({
    queryKey: depotId
      ? vehicleKeys.byDepot(scenarioId, depotId)
      : vehicleKeys.all(scenarioId),
    queryFn: () => vehicleApi.list(scenarioId, depotId),
    enabled: !!scenarioId,
  });
}

export function useVehicle(scenarioId: string, vehicleId: string) {
  return useQuery({
    queryKey: vehicleKeys.detail(scenarioId, vehicleId),
    queryFn: () => vehicleApi.get(scenarioId, vehicleId),
    enabled: !!scenarioId && !!vehicleId,
  });
}

export function useCreateVehicle(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateVehicleRequest) =>
      vehicleApi.create(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useCreateVehicleBatch(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateVehicleBatchRequest) =>
      vehicleApi.createBatch(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useUpdateVehicle(scenarioId: string, vehicleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateVehicleRequest) =>
      vehicleApi.update(scenarioId, vehicleId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: vehicleKeys.detail(scenarioId, vehicleId),
      });
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useDeleteVehicle(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vehicleId: string) =>
      vehicleApi.delete(scenarioId, vehicleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useDuplicateVehicle(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      vehicleId,
      targetDepotId,
    }: {
      vehicleId: string;
      targetDepotId?: string;
    }) => vehicleApi.duplicate(scenarioId, vehicleId, { targetDepotId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useDuplicateVehicleBatch(scenarioId: string, vehicleId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: DuplicateVehicleBatchRequest) =>
      vehicleApi.duplicateBatch(scenarioId, vehicleId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: vehicleKeys.detail(scenarioId, vehicleId) });
      qc.invalidateQueries({ queryKey: vehicleKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useVehicleTemplates(scenarioId: string) {
  return useQuery({
    queryKey: vehicleKeys.templates(scenarioId),
    queryFn: () => vehicleTemplateApi.list(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useVehicleTemplate(scenarioId: string, templateId: string) {
  return useQuery({
    queryKey: vehicleKeys.templateDetail(scenarioId, templateId),
    queryFn: () => vehicleTemplateApi.get(scenarioId, templateId),
    enabled: !!scenarioId && !!templateId,
  });
}

export function useCreateVehicleTemplate(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateVehicleTemplateRequest) =>
      vehicleTemplateApi.create(scenarioId, data),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: vehicleKeys.templates(scenarioId) }),
  });
}

export function useUpdateVehicleTemplate(
  scenarioId: string,
  templateId: string,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateVehicleTemplateRequest) =>
      vehicleTemplateApi.update(scenarioId, templateId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: vehicleKeys.templateDetail(scenarioId, templateId),
      });
      qc.invalidateQueries({ queryKey: vehicleKeys.templates(scenarioId) });
    },
  });
}

export function useDeleteVehicleTemplate(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (templateId: string) =>
      vehicleTemplateApi.delete(scenarioId, templateId),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: vehicleKeys.templates(scenarioId) }),
  });
}

// ── Route queries ─────────────────────────────────────────────

export function useRoutes(
  scenarioId: string,
  filters?: { depotId?: string; operator?: string; groupByFamily?: boolean },
) {
  return useQuery({
    queryKey: filters ? routeKeys.filtered(scenarioId, filters) : routeKeys.all(scenarioId),
    queryFn: () => routeApi.list(scenarioId, filters),
    enabled: !!scenarioId,
  });
}

export function useRoute(scenarioId: string, routeId: string) {
  return useQuery({
    queryKey: routeKeys.detail(scenarioId, routeId),
    queryFn: () => routeApi.get(scenarioId, routeId),
    enabled: !!scenarioId && !!routeId,
  });
}

export function useCreateRoute(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateRouteRequest) =>
      routeApi.create(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: routeKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useUpdateRoute(scenarioId: string, routeId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateRouteRequest) =>
      routeApi.update(scenarioId, routeId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: routeKeys.detail(scenarioId, routeId),
      });
      qc.invalidateQueries({ queryKey: routeKeys.all(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useDeleteRoute(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (routeId: string) => routeApi.delete(scenarioId, routeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: routeKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useImportOdptRoutes(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportOdptRoutesRequest) =>
      routeApi.importOdpt(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: routeKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useImportGtfsRoutes(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportGtfsRoutesRequest) =>
      routeApi.importGtfs(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: routeKeys.all(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.depotRoute(scenarioId) });
      qc.invalidateQueries({ queryKey: permissionKeys.vehicleRoute(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useStops(scenarioId: string) {
  return useQuery({
    queryKey: stopKeys.all(scenarioId),
    queryFn: () => stopApi.list(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useImportOdptStops(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportOdptStopsRequest) =>
      stopApi.importOdpt(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: stopKeys.all(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useImportGtfsStops(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data?: ImportGtfsStopsRequest) =>
      stopApi.importGtfs(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: stopKeys.all(scenarioId) });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

// ── Permission queries ────────────────────────────────────────

export function useDepotRoutePermissions(scenarioId: string) {
  return useQuery({
    queryKey: permissionKeys.depotRoute(scenarioId),
    queryFn: () => permissionApi.getDepotRoutePermissions(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useUpdateDepotRoutePermissions(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateDepotRoutePermissionsRequest) =>
      permissionApi.updateDepotRoutePermissions(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: permissionKeys.depotRoute(scenarioId),
      });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

export function useVehicleRoutePermissions(scenarioId: string) {
  return useQuery({
    queryKey: permissionKeys.vehicleRoute(scenarioId),
    queryFn: () => permissionApi.getVehicleRoutePermissions(scenarioId),
    enabled: !!scenarioId,
  });
}

export function useUpdateVehicleRoutePermissions(scenarioId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: UpdateVehicleRoutePermissionsRequest) =>
      permissionApi.updateVehicleRoutePermissions(scenarioId, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: permissionKeys.vehicleRoute(scenarioId),
      });
      invalidateDispatchOutputs(qc, scenarioId);
    },
  });
}

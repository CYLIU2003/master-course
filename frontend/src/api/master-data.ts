import { api } from "./client";
import type {
  DepotsResponse,
  DepotDetailResponse,
  CreateDepotRequest,
  UpdateDepotRequest,
  VehiclesResponse,
  VehicleDetailResponse,
  CreateVehicleRequest,
  CreateVehicleBatchRequest,
  DuplicateVehicleBatchRequest,
  UpdateVehicleRequest,
  VehicleTemplatesResponse,
  VehicleTemplateDetailResponse,
  CreateVehicleTemplateRequest,
  UpdateVehicleTemplateRequest,
  RoutesResponse,
  RouteFamiliesResponse,
  RouteFamilyDetailResponse,
  RouteDetailResponse,
  CreateRouteRequest,
  UpdateRouteRequest,
  ImportOdptRoutesRequest,
  ImportOdptRoutesResponse,
  ImportGtfsRoutesRequest,
  ImportGtfsRoutesResponse,
  StopsResponse,
  ImportOdptStopsRequest,
  ImportOdptStopsResponse,
  ImportGtfsStopsRequest,
  ImportGtfsStopsResponse,
  DepotRoutePermissionsResponse,
  DepotRouteFamilyPermissionsResponse,
  UpdateDepotRoutePermissionsRequest,
  UpdateDepotRouteFamilyPermissionsRequest,
  VehicleRoutePermissionsResponse,
  VehicleRouteFamilyPermissionsResponse,
  UpdateVehicleRoutePermissionsRequest,
  UpdateVehicleRouteFamilyPermissionsRequest,
} from "@/types";

// ── Depots ────────────────────────────────────────────────────

export const depotApi = {
  list: (scenarioId: string) =>
    api.get<DepotsResponse>(`/scenarios/${scenarioId}/depots`),

  get: (scenarioId: string, depotId: string) =>
    api.get<DepotDetailResponse>(`/scenarios/${scenarioId}/depots/${depotId}`),

  create: (scenarioId: string, data: CreateDepotRequest) =>
    api.post<DepotDetailResponse>(`/scenarios/${scenarioId}/depots`, data),

  update: (scenarioId: string, depotId: string, data: UpdateDepotRequest) =>
    api.put<DepotDetailResponse>(`/scenarios/${scenarioId}/depots/${depotId}`, data),

  delete: (scenarioId: string, depotId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/depots/${depotId}`),
};

// ── Vehicles ──────────────────────────────────────────────────

export const vehicleApi = {
  list: (scenarioId: string, depotId?: string) => {
    const query = depotId ? `?depotId=${depotId}` : "";
    return api.get<VehiclesResponse>(`/scenarios/${scenarioId}/vehicles${query}`);
  },

  get: (scenarioId: string, vehicleId: string) =>
    api.get<VehicleDetailResponse>(`/scenarios/${scenarioId}/vehicles/${vehicleId}`),

  create: (scenarioId: string, data: CreateVehicleRequest) =>
    api.post<VehicleDetailResponse>(`/scenarios/${scenarioId}/vehicles`, data),

  createBatch: (scenarioId: string, data: CreateVehicleBatchRequest) =>
    api.post<VehiclesResponse>(`/scenarios/${scenarioId}/vehicles/bulk`, data),

  update: (scenarioId: string, vehicleId: string, data: UpdateVehicleRequest) =>
    api.put<VehicleDetailResponse>(`/scenarios/${scenarioId}/vehicles/${vehicleId}`, data),

  duplicate: (
    scenarioId: string,
    vehicleId: string,
    data?: Pick<DuplicateVehicleBatchRequest, "targetDepotId">,
  ) =>
    api.post<VehicleDetailResponse>(
      `/scenarios/${scenarioId}/vehicles/${vehicleId}/duplicate`,
      data ?? {},
    ),

  duplicateBatch: (
    scenarioId: string,
    vehicleId: string,
    data: DuplicateVehicleBatchRequest,
  ) =>
    api.post<VehiclesResponse>(
      `/scenarios/${scenarioId}/vehicles/${vehicleId}/duplicate-bulk`,
      data,
    ),

  delete: (scenarioId: string, vehicleId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/vehicles/${vehicleId}`),
};

export const vehicleTemplateApi = {
  list: (scenarioId: string) =>
    api.get<VehicleTemplatesResponse>(`/scenarios/${scenarioId}/vehicle-templates`),

  get: (scenarioId: string, templateId: string) =>
    api.get<VehicleTemplateDetailResponse>(
      `/scenarios/${scenarioId}/vehicle-templates/${templateId}`,
    ),

  create: (scenarioId: string, data: CreateVehicleTemplateRequest) =>
    api.post<VehicleTemplateDetailResponse>(
      `/scenarios/${scenarioId}/vehicle-templates`,
      data,
    ),

  update: (
    scenarioId: string,
    templateId: string,
    data: UpdateVehicleTemplateRequest,
  ) =>
    api.put<VehicleTemplateDetailResponse>(
      `/scenarios/${scenarioId}/vehicle-templates/${templateId}`,
      data,
    ),

  delete: (scenarioId: string, templateId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/vehicle-templates/${templateId}`),
};

// ── Routes ────────────────────────────────────────────────────

export const routeApi = {
  list: (
    scenarioId: string,
    params?: { depotId?: string; operator?: string; groupByFamily?: boolean },
  ) => {
    const query = new URLSearchParams();
    if (params?.depotId) query.set("depotId", params.depotId);
    if (params?.operator) query.set("operator", params.operator);
    if (params?.groupByFamily) query.set("groupByFamily", "true");
    const suffix = query.size ? `?${query.toString()}` : "";
    return api.get<RoutesResponse>(`/scenarios/${scenarioId}/routes${suffix}`);
  },

  get: (scenarioId: string, routeId: string) =>
    api.get<RouteDetailResponse>(`/scenarios/${scenarioId}/routes/${routeId}`),

  create: (scenarioId: string, data: CreateRouteRequest) =>
    api.post<RouteDetailResponse>(`/scenarios/${scenarioId}/routes`, data),

  update: (scenarioId: string, routeId: string, data: UpdateRouteRequest) =>
    api.put<RouteDetailResponse>(`/scenarios/${scenarioId}/routes/${routeId}`, data),

  importOdpt: (scenarioId: string, data?: ImportOdptRoutesRequest) =>
    api.post<ImportOdptRoutesResponse>(
      `/scenarios/${scenarioId}/routes/import-odpt`,
      data,
    ),

  importGtfs: (scenarioId: string, data?: ImportGtfsRoutesRequest) =>
    api.post<ImportGtfsRoutesResponse>(
      `/scenarios/${scenarioId}/routes/import-gtfs`,
      data,
    ),

  delete: (scenarioId: string, routeId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/routes/${routeId}`),
};

export const routeFamilyApi = {
  list: (scenarioId: string, operator?: string) => {
    const query = operator ? `?operator=${operator}` : "";
    return api.get<RouteFamiliesResponse>(`/scenarios/${scenarioId}/route-families${query}`);
  },

  get: (scenarioId: string, routeFamilyId: string) =>
    api.get<RouteFamilyDetailResponse>(
      `/scenarios/${scenarioId}/route-families/${routeFamilyId}`,
    ),
};

export const stopApi = {
  list: (scenarioId: string) =>
    api.get<StopsResponse>(`/scenarios/${scenarioId}/stops`),

  importOdpt: (scenarioId: string, data?: ImportOdptStopsRequest) =>
    api.post<ImportOdptStopsResponse>(
      `/scenarios/${scenarioId}/stops/import-odpt`,
      data,
    ),

  importGtfs: (scenarioId: string, data?: ImportGtfsStopsRequest) =>
    api.post<ImportGtfsStopsResponse>(
      `/scenarios/${scenarioId}/stops/import-gtfs`,
      data,
    ),
};

// ── Permissions ───────────────────────────────────────────────

export const permissionApi = {
  getDepotRoutePermissions: (scenarioId: string) =>
    api.get<DepotRoutePermissionsResponse>(
      `/scenarios/${scenarioId}/depot-route-permissions`,
    ),

  updateDepotRoutePermissions: (
    scenarioId: string,
    data: UpdateDepotRoutePermissionsRequest,
  ) =>
    api.put<DepotRoutePermissionsResponse>(
      `/scenarios/${scenarioId}/depot-route-permissions`,
      data,
    ),

  getDepotRouteFamilyPermissions: (scenarioId: string) =>
    api.get<DepotRouteFamilyPermissionsResponse>(
      `/scenarios/${scenarioId}/depot-route-family-permissions`,
    ),

  updateDepotRouteFamilyPermissions: (
    scenarioId: string,
    data: UpdateDepotRouteFamilyPermissionsRequest,
  ) =>
    api.put<DepotRouteFamilyPermissionsResponse>(
      `/scenarios/${scenarioId}/depot-route-family-permissions`,
      data,
    ),

  getVehicleRoutePermissions: (scenarioId: string) =>
    api.get<VehicleRoutePermissionsResponse>(
      `/scenarios/${scenarioId}/vehicle-route-permissions`,
    ),

  updateVehicleRoutePermissions: (
    scenarioId: string,
    data: UpdateVehicleRoutePermissionsRequest,
  ) =>
    api.put<VehicleRoutePermissionsResponse>(
      `/scenarios/${scenarioId}/vehicle-route-permissions`,
      data,
    ),

  getVehicleRouteFamilyPermissions: (scenarioId: string) =>
    api.get<VehicleRouteFamilyPermissionsResponse>(
      `/scenarios/${scenarioId}/vehicle-route-family-permissions`,
    ),

  updateVehicleRouteFamilyPermissions: (
    scenarioId: string,
    data: UpdateVehicleRouteFamilyPermissionsRequest,
  ) =>
    api.put<VehicleRouteFamilyPermissionsResponse>(
      `/scenarios/${scenarioId}/vehicle-route-family-permissions`,
      data,
    ),
};

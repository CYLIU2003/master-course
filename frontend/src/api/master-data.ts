import { api } from "./client";
import type {
  DepotsResponse,
  DepotDetailResponse,
  CreateDepotRequest,
  UpdateDepotRequest,
  VehiclesResponse,
  VehicleDetailResponse,
  CreateVehicleRequest,
  UpdateVehicleRequest,
  RoutesResponse,
  RouteDetailResponse,
  CreateRouteRequest,
  UpdateRouteRequest,
  DepotRoutePermissionsResponse,
  UpdateDepotRoutePermissionsRequest,
  VehicleRoutePermissionsResponse,
  UpdateVehicleRoutePermissionsRequest,
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

  update: (scenarioId: string, vehicleId: string, data: UpdateVehicleRequest) =>
    api.put<VehicleDetailResponse>(`/scenarios/${scenarioId}/vehicles/${vehicleId}`, data),

  delete: (scenarioId: string, vehicleId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/vehicles/${vehicleId}`),
};

// ── Routes ────────────────────────────────────────────────────

export const routeApi = {
  list: (scenarioId: string) =>
    api.get<RoutesResponse>(`/scenarios/${scenarioId}/routes`),

  get: (scenarioId: string, routeId: string) =>
    api.get<RouteDetailResponse>(`/scenarios/${scenarioId}/routes/${routeId}`),

  create: (scenarioId: string, data: CreateRouteRequest) =>
    api.post<RouteDetailResponse>(`/scenarios/${scenarioId}/routes`, data),

  update: (scenarioId: string, routeId: string, data: UpdateRouteRequest) =>
    api.put<RouteDetailResponse>(`/scenarios/${scenarioId}/routes/${routeId}`, data),

  delete: (scenarioId: string, routeId: string) =>
    api.delete<void>(`/scenarios/${scenarioId}/routes/${routeId}`),
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
};

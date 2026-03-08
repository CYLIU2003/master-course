import { z } from "zod";

const tripSchema = z.object({
  trip_id: z.string(),
  route_id: z.string(),
  direction: z.enum(["outbound", "inbound"]),
  origin: z.string(),
  destination: z.string(),
  departure: z.string(),
  arrival: z.string(),
  departure_min: z.number().int(),
  arrival_min: z.number().int(),
  distance_km: z.number(),
  allowed_vehicle_types: z.array(z.string()),
});

const tripsResponseSchema = z.object({
  items: z.array(tripSchema),
  total: z.number().int().nonnegative(),
});

const feasibilityReasonSchema = z.enum([
  "feasible",
  "missing_deadhead",
  "insufficient_time",
  "vehicle_type_mismatch",
]);

const connectionArcSchema = z.object({
  from_trip_id: z.string(),
  to_trip_id: z.string(),
  vehicle_type: z.string(),
  deadhead_time_min: z.number().int(),
  deadhead_distance_km: z.number(),
  turnaround_time_min: z.number().int(),
  slack_min: z.number().int(),
  idle_time_min: z.number().int(),
  feasible: z.boolean(),
  reason_code: feasibilityReasonSchema,
  reason: z.string(),
});

export const graphResponseSchema = z.object({
  trips: z.array(tripSchema),
  arcs: z.array(connectionArcSchema),
  total_arcs: z.number().int().nonnegative(),
  feasible_arcs: z.number().int().nonnegative(),
  infeasible_arcs: z.number().int().nonnegative(),
  reason_counts: z.partialRecord(
    feasibilityReasonSchema,
    z.number().int().nonnegative(),
  ),
});

const dutyLegSchema = z.object({
  trip: tripSchema,
  deadhead_time_min: z.number().int(),
  deadhead_distance_km: z.number(),
});

const vehicleDutySchema = z.object({
  duty_id: z.string(),
  vehicle_type: z.string(),
  legs: z.array(dutyLegSchema),
  total_distance_km: z.number(),
  total_deadhead_km: z.number(),
  total_service_time_min: z.number().int(),
  start_time: z.string(),
  end_time: z.string(),
});

const vehicleBlockSchema = z.object({
  block_id: z.string(),
  vehicle_type: z.string(),
  trip_ids: z.array(z.string()),
});

export const dutiesResponseSchema = z.object({
  items: z.array(vehicleDutySchema),
  total: z.number().int().nonnegative(),
});

export const blocksResponseSchema = z.object({
  items: z.array(vehicleBlockSchema),
  total: z.number().int().nonnegative(),
});

export const dispatchPlanResponseSchema = z.object({
  plans: z.array(
    z.object({
      plan_id: z.string(),
      vehicle_type: z.string(),
      blocks: z.array(vehicleBlockSchema),
      duties: z.array(vehicleDutySchema),
      charging_plan: z.array(z.unknown()),
    }),
  ),
  total_plans: z.number().int().nonnegative(),
  total_blocks: z.number().int().nonnegative(),
  total_duties: z.number().int().nonnegative(),
});

export const dutyValidationResponseSchema = z.object({
  items: z.array(
    z.object({
      duty_id: z.string(),
      valid: z.boolean(),
      errors: z.array(z.string()),
    }),
  ),
  total: z.number().int().nonnegative(),
});

export const tripsListResponseSchema = tripsResponseSchema;

import assert from "node:assert/strict";
import test from "node:test";

import { buildRouteTimetables } from "../src/odpt/routeTimetables";

test("buildRouteTimetables groups patterns and trips by busroute", () => {
  const routeTimetables = buildRouteTimetables({
    stops: {
      S1: { stop_id: "S1", name: "Start" },
      S2: { stop_id: "S2", name: "Middle" },
      S3: { stop_id: "S3", name: "End" },
    },
    routePatterns: {
      "odpt.BusroutePattern:TokyuBus.A24.out": {
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.out",
        title: "A24 Start-End",
        note: undefined,
        busroute: "odpt.Busroute:TokyuBus.A24",
        stop_sequence: ["S1", "S2", "S3"],
        segments: [],
        total_distance_km: 12.5,
        distance_coverage_ratio: 1,
      },
      "odpt.BusroutePattern:TokyuBus.A24.in": {
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.in",
        title: "A24 End-Start",
        note: undefined,
        busroute: "odpt.Busroute:TokyuBus.A24",
        stop_sequence: ["S3", "S2", "S1"],
        segments: [],
        total_distance_km: 12.5,
        distance_coverage_ratio: 1,
      },
    },
    trips: {
      "trip-out-1": {
        trip_id: "trip-out-1",
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.out",
        calendar: "odpt.Calendar:Weekday",
        service_id: "weekday",
        stop_times: [
          { index: 0, stop_id: "S1", departure: "08:00" },
          { index: 1, stop_id: "S2", arrival: "08:10", departure: "08:11" },
          { index: 2, stop_id: "S3", arrival: "08:22" },
        ],
        distance_source: "pattern_segments",
        estimated_distance_km: 12.5,
      },
      "trip-in-1": {
        trip_id: "trip-in-1",
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.in",
        calendar: "odpt.Calendar:Saturday",
        service_id: "saturday",
        stop_times: [
          { index: 0, stop_id: "S3", departure: "09:00" },
          { index: 1, stop_id: "S2", arrival: "09:12", departure: "09:13" },
          { index: 2, stop_id: "S1", arrival: "09:25" },
        ],
        distance_source: "pattern_segments",
        estimated_distance_km: 12.5,
      },
    },
    stopTimetables: {},
    indexes: {
      tripsByService: {
        weekday: ["trip-out-1"],
        saturday: ["trip-in-1"],
        holiday: [],
        unknown: [],
      },
      tripsByPattern: {
        "odpt.BusroutePattern:TokyuBus.A24.out": ["trip-out-1"],
        "odpt.BusroutePattern:TokyuBus.A24.in": ["trip-in-1"],
      },
    },
  });

  assert.equal(routeTimetables.length, 1);

  const route = routeTimetables[0];
  assert.equal(route.busroute_id, "odpt.Busroute:TokyuBus.A24");
  assert.equal(route.route_code, "A24");
  assert.equal(route.route_label, "A24 Start-End");
  assert.equal(route.trip_count, 2);
  assert.equal(route.first_departure, "08:00");
  assert.equal(route.last_arrival, "09:25");

  assert.deepEqual(
    route.patterns.map((pattern) => ({
      pattern_id: pattern.pattern_id,
      direction: pattern.direction,
      stops: pattern.stop_sequence.map((stop) => stop.stop_name),
    })),
    [
      {
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.in",
        direction: "inbound",
        stops: ["End", "Middle", "Start"],
      },
      {
        pattern_id: "odpt.BusroutePattern:TokyuBus.A24.out",
        direction: "outbound",
        stops: ["Start", "Middle", "End"],
      },
    ],
  );

  assert.deepEqual(
    route.services.map((service) => ({
      service_id: service.service_id,
      trip_count: service.trip_count,
      first_departure: service.first_departure,
      last_arrival: service.last_arrival,
    })),
    [
      {
        service_id: "weekday",
        trip_count: 1,
        first_departure: "08:00",
        last_arrival: "08:22",
      },
      {
        service_id: "saturday",
        trip_count: 1,
        first_departure: "09:00",
        last_arrival: "09:25",
      },
    ],
  );

  assert.deepEqual(
    route.trips.map((trip) => ({
      trip_id: trip.trip_id,
      direction: trip.direction,
      departure: trip.departure,
      arrival: trip.arrival,
      stops: trip.stop_times.map((stopTime) => ({
        stop_name: stopTime.stop_name,
        time: stopTime.time,
      })),
    })),
    [
      {
        trip_id: "trip-out-1",
        direction: "outbound",
        departure: "08:00",
        arrival: "08:22",
        stops: [
          { stop_name: "Start", time: "08:00" },
          { stop_name: "Middle", time: "08:11" },
          { stop_name: "End", time: "08:22" },
        ],
      },
      {
        trip_id: "trip-in-1",
        direction: "inbound",
        departure: "09:00",
        arrival: "09:25",
        stops: [
          { stop_name: "End", time: "09:00" },
          { stop_name: "Middle", time: "09:13" },
          { stop_name: "Start", time: "09:25" },
        ],
      },
    ],
  );
});

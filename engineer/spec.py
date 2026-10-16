"""F1 25 2026 Season Pack UDP layouts (packet format 2026, spec v1.2).

Field names drop the m_ prefix but otherwise match the spec so it can be
grepped against docs/udp-spec-2026.txt. Wheel arrays are RL, RR, FL, FR.
"""
from .codec import F, Str, Struct

FORMAT = 2026
MAX_CARS = 24

HEADER = Struct("PacketHeader", [
    F("packetFormat", "H"),
    F("gameYear", "B"),
    F("gameMajorVersion", "B"),
    F("gameMinorVersion", "B"),
    F("packetVersion", "B"),
    F("packetId", "B"),
    F("sessionUID", "Q"),
    F("sessionTime", "f"),
    F("frameIdentifier", "I"),
    F("overallFrameIdentifier", "I"),
    F("playerCarIndex", "B"),
    F("secondaryPlayerCarIndex", "B"),
])


def packet(name, fields):
    return Struct(name, [F("header", HEADER)] + fields)


# 0 ---------------------------------------------------------------------------

CAR_MOTION = Struct("CarMotionData", [
    F("worldPositionX", "f"), F("worldPositionY", "f"), F("worldPositionZ", "f"),
    F("worldVelocityX", "f"), F("worldVelocityY", "f"), F("worldVelocityZ", "f"),
    F("worldForwardDirX", "h", scale=32767.0), F("worldForwardDirY", "h", scale=32767.0),
    F("worldForwardDirZ", "h", scale=32767.0),
    F("worldRightDirX", "h", scale=32767.0), F("worldRightDirY", "h", scale=32767.0),
    F("worldRightDirZ", "h", scale=32767.0),
    F("gForceLateral", "h", scale=1000.0), F("gForceLongitudinal", "h", scale=1000.0),
    F("gForceVertical", "h", scale=1000.0),
    F("yaw", "f"), F("pitch", "f"), F("roll", "f"),
])

MOTION = packet("Motion", [F("carMotionData", CAR_MOTION, MAX_CARS)])

# 1 ---------------------------------------------------------------------------

MARSHAL_ZONE = Struct("MarshalZone", [F("zoneStart", "f"), F("zoneFlag", "b")])
ZONE = Struct("Zone", [F("zoneStart", "f"), F("zoneEnd", "f")])

WEATHER_SAMPLE = Struct("WeatherForecastSample", [
    F("sessionType", "B"),
    F("timeOffset", "B"),
    F("weather", "B"),
    F("trackTemperature", "b"),
    F("trackTemperatureChange", "b"),
    F("airTemperature", "b"),
    F("airTemperatureChange", "b"),
    F("rainPercentage", "B"),
])

_u8 = lambda *names: [F(n, "B") for n in names]

SESSION = packet("Session", [
    F("weather", "B"),
    F("trackTemperature", "b"),
    F("airTemperature", "b"),
    F("totalLaps", "B"),
    F("trackLength", "H"),
    F("sessionType", "B"),
    F("trackId", "b"),
    F("formula", "B"),
    F("sessionTimeLeft", "H"),
    F("sessionDuration", "H"),
    *_u8("pitSpeedLimit", "gamePaused", "isSpectating", "spectatorCarIndex",
         "sliProNativeSupport", "numMarshalZones"),
    F("marshalZones", MARSHAL_ZONE, 21),
    *_u8("safetyCarStatus", "networkGame", "numWeatherForecastSamples"),
    F("weatherForecastSamples", WEATHER_SAMPLE, 64),
    *_u8("forecastAccuracy", "aiDifficulty"),
    F("seasonLinkIdentifier", "I"),
    F("weekendLinkIdentifier", "I"),
    F("sessionLinkIdentifier", "I"),
    *_u8("pitStopWindowIdealLap", "pitStopWindowLatestLap", "pitStopRejoinPosition",
         "steeringAssist", "brakingAssist", "gearboxAssist", "pitAssist", "pitReleaseAssist",
         "ERSAssist", "DRSAssist", "dynamicRacingLine", "dynamicRacingLineType",
         "gameMode", "ruleSet"),
    F("timeOfDay", "I"),
    *_u8("sessionLength", "speedUnitsLeadPlayer", "temperatureUnitsLeadPlayer",
         "speedUnitsSecondaryPlayer", "temperatureUnitsSecondaryPlayer",
         "numSafetyCarPeriods", "numVirtualSafetyCarPeriods", "numRedFlagPeriods",
         "equalCarPerformance", "recoveryMode", "flashbackLimit", "surfaceType",
         "lowFuelMode", "raceStarts", "tyreTemperature", "pitLaneTyreSim", "carDamage",
         "carDamageRate", "collisions", "collisionsOffForFirstLapOnly", "mpUnsafePitRelease",
         "mpOffForGriefing", "cornerCuttingStringency", "parcFermeRules", "pitStopExperience",
         "safetyCar", "safetyCarExperience", "formationLap", "formationLapExperience",
         "redFlags", "affectsLicenceLevelSolo", "affectsLicenceLevelMP", "numSessionsInWeekend"),
    F("weekendStructure", "B", 12),
    F("sector2LapDistanceStart", "f"),
    F("sector3LapDistanceStart", "f"),
    *_u8("activeAeroTrackStatus", "numActiveAeroZonesFull"),
    F("activeAeroZonesFull", ZONE, 8),
    F("numActiveAeroZonesPartial", "B"),
    F("activeAeroZonesPartial", ZONE, 8),
    F("numDRSZones", "B"),
    F("drsZones", ZONE, 4),
    F("startReactionTime", "f"),
    *_u8("antiLockBrakesAssist", "tractionControlAssist", "dynamicRacingLineHiVis",
         "dynamicRacingLineColourBlind", "recurringRewindPrompt"),
])

# 2 ---------------------------------------------------------------------------

LAP = Struct("LapData", [
    F("lastLapTimeInMS", "I"),
    F("currentLapTimeInMS", "I"),
    F("sector1TimeMSPart", "H"), F("sector1TimeMinutesPart", "B"),
    F("sector2TimeMSPart", "H"), F("sector2TimeMinutesPart", "B"),
    F("deltaToCarInFrontMSPart", "H"), F("deltaToCarInFrontMinutesPart", "B"),
    F("deltaToRaceLeaderMSPart", "H"), F("deltaToRaceLeaderMinutesPart", "B"),
    F("lapDistance", "f"),
    F("totalDistance", "f"),
    F("safetyCarDelta", "f"),
    *_u8("carPosition", "currentLapNum", "pitStatus", "numPitStops", "sector",
         "currentLapInvalid", "penalties", "totalWarnings", "cornerCuttingWarnings",
         "numUnservedDriveThroughPens", "numUnservedStopGoPens", "gridPosition",
         "driverStatus", "resultStatus", "pitLaneTimerActive"),
    F("pitLaneTimeInLaneInMS", "H"),
    F("pitStopTimerInMS", "H"),
    F("pitStopShouldServePen", "B"),
    F("speedTrapFastestSpeed", "f"),
    F("speedTrapFastestLap", "B"),
])

LAP_DATA = packet("LapData", [
    F("lapData", LAP, MAX_CARS),
    F("timeTrialPBCarIdx", "B"),
    F("timeTrialRivalCarIdx", "B"),
])

# 3 ---------------------------------------------------------------------------

EVENT_DETAILS_SIZE = 12

EVENT = packet("Event", [
    F("eventStringCode", Str(4)),
    F("eventDetails", f"{EVENT_DETAILS_SIZE}s"),
])

EVENT_DETAILS = {
    "FTLP": Struct("FastestLap", [F("vehicleIdx", "B"), F("lapTime", "f")]),
    "RTMT": Struct("Retirement", _u8("vehicleIdx", "reason")),
    "DRSD": Struct("DRSDisabled", _u8("reason")),
    "TMPT": Struct("TeamMateInPits", _u8("vehicleIdx")),
    "RCWN": Struct("RaceWinner", _u8("vehicleIdx")),
    "PENA": Struct("Penalty", _u8("penaltyType", "infringementType", "vehicleIdx",
                                  "otherVehicleIdx", "time", "lapNum", "placesGained")),
    "SPTP": Struct("SpeedTrap", [
        F("vehicleIdx", "B"), F("speed", "f"), F("isOverallFastestInSession", "B"),
        F("isDriverFastestInSession", "B"), F("fastestVehicleIdxInSession", "B"),
        F("fastestSpeedInSession", "f"),
    ]),
    "STLG": Struct("StartLights", _u8("numLights")),
    "DTSV": Struct("DriveThroughPenaltyServed", _u8("vehicleIdx")),
    "SGSV": Struct("StopGoPenaltyServed", [F("vehicleIdx", "B"), F("stopTime", "f")]),
    "FLBK": Struct("Flashback", [F("flashbackFrameIdentifier", "I"), F("flashbackSessionTime", "f")]),
    "BUTN": Struct("Buttons", [F("buttonStatus", "I")]),
    "OVTK": Struct("Overtake", _u8("overtakingVehicleIdx", "beingOvertakenVehicleIdx")),
    "SCAR": Struct("SafetyCar", _u8("safetyCarType", "eventType")),
    "COLL": Struct("Collision", _u8("vehicle1Idx", "vehicle2Idx", "severity")),
    "PMEN": Struct("PartialModeEnabled", _u8("reason")),
}

# 4 ---------------------------------------------------------------------------

LIVERY_COLOUR = Struct("LiveryColour", _u8("red", "green", "blue"))

PARTICIPANT = Struct("ParticipantData", [
    F("aiControlled", "B"),
    F("driverId", "H"),
    F("networkId", "H"),
    F("teamId", "H"),
    *_u8("myTeam", "raceNumber", "nationality"),
    F("name", Str(32)),
    *_u8("yourTelemetry", "showOnlineNames"),
    F("techLevel", "H"),
    *_u8("platform", "numColours"),
    F("liveryColours", LIVERY_COLOUR, 4),
])

PARTICIPANTS = packet("Participants", [
    F("numActiveCars", "B"),
    F("participants", PARTICIPANT, MAX_CARS),
])

# 5 ---------------------------------------------------------------------------

CAR_SETUP = Struct("CarSetupData", [
    *_u8("frontWing", "rearWing", "onThrottle", "offThrottle"),
    F("frontCamber", "f"), F("rearCamber", "f"), F("frontToe", "f"), F("rearToe", "f"),
    *_u8("frontSuspension", "rearSuspension", "frontAntiRollBar", "rearAntiRollBar",
         "frontSuspensionHeight", "rearSuspensionHeight", "brakePressure", "brakeBias",
         "engineBraking"),
    F("rearLeftTyrePressure", "f"), F("rearRightTyrePressure", "f"),
    F("frontLeftTyrePressure", "f"), F("frontRightTyrePressure", "f"),
    F("ballast", "B"),
    F("fuelLoad", "f"),
])

CAR_SETUPS = packet("CarSetups", [
    F("carSetups", CAR_SETUP, MAX_CARS),
    F("nextFrontWingValue", "f"),
])

# 6 ---------------------------------------------------------------------------

CAR_TELEMETRY = Struct("CarTelemetryData", [
    F("speed", "H"),
    F("throttle", "f"),
    F("steer", "f"),
    F("brake", "f"),
    F("clutch", "B"),
    F("gear", "b"),
    F("engineRPM", "H"),
    F("drs", "B"),
    F("revLightsPercent", "B"),
    F("revLightsBitValue", "H"),
    F("brakesTemperature", "H", 4),
    F("tyresSurfaceTemperature", "B", 4),
    F("tyresInnerTemperature", "B", 4),
    F("engineTemperature", "B"),
    F("tyresPressure", "f", 4),
    F("surfaceType", "B", 4),
])

CAR_TELEMETRY_PACKET = packet("CarTelemetry", [
    F("carTelemetryData", CAR_TELEMETRY, MAX_CARS),
    F("mfdPanelIndex", "B"),
    F("mfdPanelIndexSecondaryPlayer", "B"),
    F("suggestedGear", "b"),
])

# 7 ---------------------------------------------------------------------------

CAR_STATUS = Struct("CarStatusData", [
    *_u8("tractionControl", "antiLockBrakes", "fuelMix", "frontBrakeBias", "pitLimiterStatus"),
    F("fuelInTank", "f"),
    F("fuelCapacity", "f"),
    F("fuelRemainingLaps", "f"),
    F("maxRPM", "H"),
    F("idleRPM", "H"),
    *_u8("maxGears", "drsAllowed"),
    F("drsActivationDistance", "H"),
    *_u8("actualTyreCompound", "visualTyreCompound", "tyresAgeLaps"),
    F("vehicleFiaFlags", "b"),
    F("enginePowerICE", "f"),
    F("enginePowerMGUK", "f"),
    F("ersStoreEnergy", "f"),
    F("ersDeployMode", "B"),
    F("ersHarvestedThisLapMGUK", "f"),
    F("ersHarvestedThisLapMGUH", "f"),
    F("ersHarvestedLimitPerLap", "f"),
    F("ersDeployedThisLap", "f"),
    F("networkPaused", "B"),
])

CAR_STATUS_PACKET = packet("CarStatus", [F("carStatusData", CAR_STATUS, MAX_CARS)])

# 8 ---------------------------------------------------------------------------

FINAL_CLASSIFICATION = Struct("FinalClassificationData", [
    *_u8("position", "numLaps", "gridPosition", "points", "numPitStops", "resultStatus",
         "resultReason"),
    F("bestLapTimeInMS", "I"),
    F("totalRaceTime", "d"),
    *_u8("penaltiesTime", "numPenalties", "numTyreStints"),
    F("tyreStintsActual", "B", 8),
    F("tyreStintsVisual", "B", 8),
    F("tyreStintsEndLaps", "B", 8),
])

FINAL_CLASSIFICATION_PACKET = packet("FinalClassification", [
    F("numCars", "B"),
    F("classificationData", FINAL_CLASSIFICATION, MAX_CARS),
])

# 9 ---------------------------------------------------------------------------

LOBBY_PLAYER = Struct("LobbyInfoData", [
    F("aiControlled", "B"),
    F("teamId", "H"),
    *_u8("nationality", "platform"),
    F("name", Str(32)),
    *_u8("carNumber", "yourTelemetry", "showOnlineNames"),
    F("techLevel", "H"),
    F("readyStatus", "B"),
])

LOBBY_INFO = packet("LobbyInfo", [
    F("numPlayers", "B"),
    F("lobbyPlayers", LOBBY_PLAYER, MAX_CARS),
])

# 10 --------------------------------------------------------------------------

CAR_DAMAGE = Struct("CarDamageData", [
    F("tyresWear", "f", 4),
    F("tyresDamage", "B", 4),
    F("brakesDamage", "B", 4),
    F("tyreBlisters", "B", 4),
    *_u8("frontLeftWingDamage", "frontRightWingDamage", "rearWingDamage", "floorDamage",
         "diffuserDamage", "sidepodDamage", "drsFault", "ersFault", "gearBoxDamage",
         "engineDamage", "engineMGUHWear", "engineESWear", "engineCEWear", "engineICEWear",
         "engineMGUKWear", "engineTCWear", "engineBlown", "engineSeized"),
])

CAR_DAMAGE_PACKET = packet("CarDamage", [F("carDamageData", CAR_DAMAGE, MAX_CARS)])

# 11 --------------------------------------------------------------------------

LAP_HISTORY = Struct("LapHistoryData", [
    F("lapTimeInMS", "I"),
    F("sector1TimeMSPart", "H"), F("sector1TimeMinutesPart", "B"),
    F("sector2TimeMSPart", "H"), F("sector2TimeMinutesPart", "B"),
    F("sector3TimeMSPart", "H"), F("sector3TimeMinutesPart", "B"),
    F("lapValidBitFlags", "B"),
])

TYRE_STINT = Struct("TyreStintHistoryData", _u8("endLap", "tyreActualCompound", "tyreVisualCompound"))

SESSION_HISTORY = packet("SessionHistory", [
    *_u8("carIdx", "numLaps", "numTyreStints", "bestLapTimeLapNum", "bestSector1LapNum",
         "bestSector2LapNum", "bestSector3LapNum"),
    F("lapHistoryData", LAP_HISTORY, 100),
    F("tyreStintsHistoryData", TYRE_STINT, 8),
])

# 12 --------------------------------------------------------------------------

TYRE_SET = Struct("TyreSetData", [
    *_u8("actualTyreCompound", "visualTyreCompound", "wear", "available", "recommendedSession",
         "lifeSpan", "usableLife"),
    F("lapDeltaTime", "h"),
    F("fitted", "B"),
])

TYRE_SETS = packet("TyreSets", [
    F("carIdx", "B"),
    F("tyreSetData", TYRE_SET, 20),
    F("fittedIdx", "B"),
])

# 13 --------------------------------------------------------------------------

_wheels = lambda *names: [F(n, "f", 4) for n in names]
_floats = lambda *names: [F(n, "f") for n in names]

MOTION_EX = packet("MotionEx", [
    *_wheels("suspensionPosition", "suspensionVelocity", "suspensionAcceleration", "wheelSpeed",
             "wheelSlipRatio", "wheelSlipAngle", "wheelLatForce", "wheelLongForce"),
    *_floats("heightOfCOGAboveGround", "localVelocityX", "localVelocityY", "localVelocityZ",
             "angularVelocityX", "angularVelocityY", "angularVelocityZ",
             "angularAccelerationX", "angularAccelerationY", "angularAccelerationZ",
             "frontWheelsAngle"),
    *_wheels("wheelVertForce"),
    *_floats("frontAeroHeight", "rearAeroHeight", "frontRollAngle", "rearRollAngle",
             "chassisYaw", "chassisPitch"),
    *_wheels("wheelCamber", "wheelCamberGain"),
])

# 14 --------------------------------------------------------------------------

TIME_TRIAL_SET = Struct("TimeTrialDataSet", [
    F("carIdx", "B"),
    F("teamId", "H"),
    F("lapTimeInMS", "I"),
    F("sector1TimeInMS", "I"),
    F("sector2TimeInMS", "I"),
    F("sector3TimeInMS", "I"),
    *_u8("tractionControl", "gearboxAssist", "antiLockBrakes", "equalCarPerformance",
         "customSetup", "valid"),
])

TIME_TRIAL = packet("TimeTrial", [
    F("playerSessionBestDataSet", TIME_TRIAL_SET),
    F("personalBestDataSet", TIME_TRIAL_SET),
    F("rivalDataSet", TIME_TRIAL_SET),
])

# 15 --------------------------------------------------------------------------

LAP_POSITIONS = packet("LapPositions", [
    F("numLaps", "B"),
    F("lapStart", "B"),
    # [50][24]: one row per lap, position per vehicle index, 0 = no record
    F("positionForVehicleIdx", Struct("LapRow", [F("positions", "B", MAX_CARS)]), 50),
])

# 16 --------------------------------------------------------------------------

CAR_TELEMETRY_2 = Struct("CarTelemetry2Data", [
    *_u8("activeAeroMode", "activeAeroAvailable"),
    F("activeAeroActivationDistance", "H"),
    *_u8("overtakeAvailable", "overtakeActive"),
    F("overtakeActivationDistance", "H"),
    *_u8("is2026Regulations", "drivingWrongWay"),  # spec: m_2026Regulations
])

CAR_TELEMETRY_2_PACKET = packet("CarTelemetry2", [F("carTelemetry2Data", CAR_TELEMETRY_2, MAX_CARS)])

# -----------------------------------------------------------------------------

PACKETS = {
    0: MOTION,
    1: SESSION,
    2: LAP_DATA,
    3: EVENT,
    4: PARTICIPANTS,
    5: CAR_SETUPS,
    6: CAR_TELEMETRY_PACKET,
    7: CAR_STATUS_PACKET,
    8: FINAL_CLASSIFICATION_PACKET,
    9: LOBBY_INFO,
    10: CAR_DAMAGE_PACKET,
    11: SESSION_HISTORY,
    12: TYRE_SETS,
    13: MOTION_EX,
    14: TIME_TRIAL,
    15: LAP_POSITIONS,
    16: CAR_TELEMETRY_2_PACKET,
}

# "Size:" line under each packet in the spec
SPEC_SIZES = {
    0: 1325, 1: 926, 2: 1399, 3: 45, 4: 1470, 5: 1233, 6: 1448, 7: 1445, 8: 1134,
    9: 1062, 10: 1133, 11: 1460, 12: 231, 13: 273, 14: 104, 15: 1231, 16: 269,
}

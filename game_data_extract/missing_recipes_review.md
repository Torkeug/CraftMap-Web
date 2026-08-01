# Missing recipes review

114 of 479 game recipes have no matching resources.db recipe yet. Proposed names are suggestions only - edit before hand-entering.

(11 additional game recipes excluded above: `unlockType: 0` but no `permit` sheet entry actually grants them, so they're unreachable in normal play - see game_data_extract/README.md's `unlockType` note.)

## BaseBuilding (17)

- **Antimatter Synthesizer** (`AntimatterSynthPH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 10x Structural Beam, 10x Stainless Plate
  - outputs: 1x Antimatter Synthesizer

- **Atmo-dome Generator** (`AtmoDomePH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 4x Structural Beam, 3x Stainless Plate
  - outputs: 1x Atmo-dome Generator

- **Cable** (`Cable0`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 1x Wire
  - outputs: 1x Cable

- **Diver Hologram** (`DecoDiver`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Diver Hologram

- **Pirate Hologram** (`DecoPirate`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Pirate Hologram

- **Planet Hologram** (`DecoPlanet`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Planet Hologram

- **Sakura Hologram** (`DecoSakura`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Sakura Hologram

- **Snake Hologram** (`DecoSnake`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Snake Hologram

- **Test deco** (`DecoTest`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Test deco

- **Transcendance Hologram** (`DecoTranscendance`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 
  - outputs: 1x Transcendance Hologram

- **Advanced Extractor** (`Extractor1PH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 4x Heavy-Duty Beam, 10x Inert Plate, 3x Simple Mining Laser, 2x Motor, 20x Concrete
  - outputs: 1x Advanced Extractor

- **Cosmic Condenser** (`FTLGathererPH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 4x Structural Beam, 3x Stainless Plate
  - outputs: 1x Cosmic Condenser

- **Advanced Fuel Power Plant** (`FuelGenerator1PH`) - station: <bad>Cannot Craft In Beta</bad>, auto: 0s, manual: 0s
  - inputs: 4x Structural Beam, 4x Stainless Plate, 1x Motor, 40x Concrete
  - outputs: 1x Advanced Fuel Power Plant

- **Fusion Plant** (`FusionCentral0PH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 1x Structural Beam, 36x Stainless Plate, 216x Solar Cell
  - outputs: 1x Fusion Plant

- **Hypergate** (`HypergatePH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 1x Landing Pad, 12x Structural Beam, 12x Stainless Plate
  - outputs: 1x Hypergate

- **Observatory** (`ObservatoryPH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 4x Structural Beam, 3x Stainless Plate
  - outputs: 1x Observatory

- **Sun Station** (`SunStationPH`) - station: Construction, auto: 0s, manual: 0s
  - inputs: 1x Structural Beam, 36x Stainless Plate, 216x Solar Cell
  - outputs: 1x Sun Station

## Craft_Casings (2)

- **Small Alloy X Part Casing** (`AlloyXCasingMK1`) - station: Assembler, auto: 720s, manual: 0s
  - inputs: 
  - outputs: 1x Small Alloy X Part Casing

- **Alloy X Part Casing** (`AlloyXCasingMK2`) - station: Factory, auto: 1440s, manual: 0s
  - inputs: 2x Small Alloy X Part Casing
  - outputs: 1x Alloy X Part Casing

## Craft_Dismantle (32)

- **Steel Scraps (Battery Array)** (`Dismantle_B_Battery`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Battery Array
  - outputs: 4x Steel Scraps, 2x Stainless Plate, 50x Chemical Battery, 2x Magnetic Coil

- **Industrial Rubble (Bottling Plant)** (`Dismantle_B_BottlingPlant`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Bottling Plant
  - outputs: 1x Industrial Rubble, 1x Iron Scraps, 1x Titanium Scraps, 0x Pump, 5x Watertight Pipe, 5x Stainless Plate

- **Steel Scraps (Chemical Factory)** (`Dismantle_B_ChemFactory`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Chemical Factory
  - outputs: 8x Steel Scraps, 8x Industrial Rubble, 36x Stainless Plate, 3x Pump, 60x Watertight Pipe

- **Metal Sheet (Trading Box)** (`Dismantle_B_Chest`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Trading Box
  - outputs: 10x Metal Sheet

- **Industrial Rubble (Cistern)** (`Dismantle_B_Cistern`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Cistern
  - outputs: 4x Industrial Rubble, 5x Pump, 50x Watertight Pipe, 38x Stainless Plate

- **Wire (Cable)** (`Dismantle_B_Connector`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Cable
  - outputs: 1x Wire

- **Base Core Drive** (`Dismantle_B_ControlBase`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Base Command Center
  - outputs: 1x Base Core Drive, 4x Industrial Rubble, 5x Iron Scraps, 10x Wire

- **Industrial Rubble (Command Tower)** (`Dismantle_B_ControlBase2`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Command Tower
  - outputs: 50x Industrial Rubble, 25x Steel Scraps, 16x Iron Scraps, 80x Wire, 8x Magnetic Coil

- **Industrial Rubble (Command Relay)** (`Dismantle_B_ControlBase2PH`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Command Relay
  - outputs: 1x Industrial Rubble, 0x Iron Scraps

- **Industrial Rubble (Corporation Command Center)** (`Dismantle_B_ControlBase3`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Corporation Command Center
  - outputs: 2000x Industrial Rubble, 4000x Steel Scraps, 1200x Iron Scraps, 6000x Wire, 600x Magnetic Coil

- **Steel Scraps (Crystallizer)** (`Dismantle_B_Crystaliser`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Crystallizer
  - outputs: 2x Steel Scraps, 2x Industrial Rubble, 4x Stainless Plate, 5x Watertight Pipe

- **Magnetic Coil (Pylon)** (`Dismantle_B_ElectricPillar`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Pylon
  - outputs: 1x Magnetic Coil

- **Motor (Extractor)** (`Dismantle_B_Extractor`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Extractor
  - outputs: 0x Motor, 2x Concrete

- **Industrial Rubble (Mag-Plasma Cistern)** (`Dismantle_B_FTLCistern`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Mag-Plasma Cistern
  - outputs: 4x Industrial Rubble, 5x Confinement Chamber, 5x Monomagnetic Sheet

- **Steel Scraps (Assembler)** (`Dismantle_B_Factory1`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Assembler
  - outputs: 4x Steel Scraps, 8x Industrial Rubble, 2x Motor

- **Steel Scraps (Factory)** (`Dismantle_B_Factory2`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Factory
  - outputs: 40x Steel Scraps, 40x Industrial Rubble, 5x Motor, 5x Microchip, 2x Hydraulic Actuator

- **Steel Scraps (Xenic Farm)** (`Dismantle_B_Farm`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Xenic Farm
  - outputs: 10x Steel Scraps, 10x Industrial Rubble, 2x Pump, 30x Watertight Pipe

- **Industrial Rubble (Fuel Power Plant)** (`Dismantle_B_Generator`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Fuel Power Plant
  - outputs: 1x Industrial Rubble, 5x Steel Scraps, 5x Motor

- **Ciliary Lens (Laboratory)** (`Dismantle_B_Labo`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Laboratory
  - outputs: 1x Ciliary Lens, 2x Stainless Plate, 2x Motor

- **Industrial Rubble (Landing Pad)** (`Dismantle_B_LandingPad`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Landing Pad
  - outputs: 8x Industrial Rubble

- **Steel Scraps (Liquid Extractor)** (`Dismantle_B_LiquidExtractor`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Liquid Extractor
  - outputs: 4x Steel Scraps, 4x Industrial Rubble, 18x Stainless Plate, 10x Pump, 40x Watertight Pipe

- **Metal Sheet (Drone Dispatcher)** (`Dismantle_B_Organiser`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Drone Dispatcher
  - outputs: 1x Metal Sheet, 1x Stainless Plate

- **Steel Scraps (Pathway Stand)** (`Dismantle_B_PathwayHolder`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Pathway Stand
  - outputs: 12x Steel Scraps, 18x Industrial Rubble, 6x Stainless Plate, 0x Calcified Invariant, 1x Magnetic Coil

- **Steel Scraps (Power Transmitter)** (`Dismantle_B_PowerTransmiterPH`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Power Transmitter
  - outputs: 2x Steel Scraps, 5x Industrial Rubble, 0x Quantic Graphenoid

- **Industrial Rubble (Recycling Plant)** (`Dismantle_B_RecyclingPlant`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Recycling Plant
  - outputs: 10x Industrial Rubble, 8x Steel Scraps, 5x Stainless Plate, 3x Motor

- **Industrial Rubble (Shipyard)** (`Dismantle_B_Shipyard`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Shipyard
  - outputs: 18x Industrial Rubble, 12x Steel Scraps, 6x Stainless Plate

- **Steel Scraps (Shuttle Landing Pad)** (`Dismantle_B_ShuttlePad`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Shuttle Landing Pad
  - outputs: 2x Steel Scraps, 4x Industrial Rubble, 6x Iron Scraps, 0x Calcified Invariant, 1x Magnetic Coil

- **Industrial Rubble (Smelter)** (`Dismantle_B_Smelter`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Smelter
  - outputs: 1x Industrial Rubble, 3x Concrete

- **Stainless Plate (Micro-Furnace)** (`Dismantle_B_SmelterSA`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Micro-Furnace
  - outputs: 2x Stainless Plate, 5x Concrete, 1x Calcite

- **Steel Scraps (Solar Plant)** (`Dismantle_B_SolarPanel`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Solar Plant
  - outputs: 1x Steel Scraps, 5x Stainless Plate, 18x Solar Cell

- **Stainless Plate (Stand-alone Foundation)** (`Dismantle_B_StandaloneFoundation`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Stand-alone Foundation
  - outputs: 1x Stainless Plate, 5x Concrete

- **Iron Scraps** (`Dismantle_B_Warehouse`) - station: (none), auto: 0s, manual: 0s
  - inputs: 1x Warehouse
  - outputs: 12x Iron Scraps, 4x Industrial Rubble, 4x Steel Scraps

## Craft_IntermediaryComponent (1)

- **Antimatter Core (empty) (Magnetic Coil)** (`AntimatterCorePH`) - station: <bad>Cannot Craft In Beta</bad>, auto: 0s, manual: 0s
  - inputs: 2x Magnetic Coil
  - outputs: 1x Antimatter Core (empty)

## Craft_Modules (7)

- **Big Mag-Plasma Tank** (`FTLTank3PH`) - station: Factory, auto: 1440s, manual: 0s
  - inputs: 1x Large Module Kit, 1x Small Pressure Chamber, 1x Confinement Chamber
  - outputs: 1x Big Mag-Plasma Tank

- **Fusion Generator** (`FusionGenPH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Fusion Generator

- **Heat Condenser** (`HeatRecoup_ShipPH`) - station: <bad>Cannot Craft In Beta</bad>, auto: 0s, manual: 0s
  - inputs: 1x Module Kit, 1x Small Pressure Chamber, 1x Confinement Chamber
  - outputs: 1x Heat Condenser

- **Thermal Shield** (`HeatShieldPH`) - station: Workshop, auto: 2250s, manual: 25s
  - inputs: 1x Module Kit, 1x Small Pressure Chamber, 1x Confinement Chamber
  - outputs: 1x Thermal Shield

- **Isotopic Generator** (`IsotopicGenPH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Isotopic Generator

- **Kinetic Shield Projector** (`KineticShieldGroupPH`) - station: Workshop, auto: 2250s, manual: 25s
  - inputs: 1x Module Kit, 1x Small Pressure Chamber, 1x Confinement Chamber
  - outputs: 1x Kinetic Shield Projector

- **Paradoxical Battery** (`PbatteryPH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Paradoxical Battery

## Craft_Other (7)

- **Anti-matter Torpedo** (`AntiMatterMissilePH`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 1x Antimatter Core (full), 1x Small Missile Airframe
  - outputs: 3x Anti-matter Torpedo

- **Antimatter Core (empty) (Antimatter Core (full))** (`AntimatterToPower`) - station: <bad>Cannot Craft In Beta</bad>, auto: 2400s, manual: 0s
  - inputs: 1x Antimatter Core (full)
  - outputs: 1x Antimatter Core (empty)

- **Hypergate Beacon** (`HypergateBeaconPH`) - station: Workshop, auto: 450s, manual: 5s
  - inputs: 2x Magnetic Coil
  - outputs: 1x Hypergate Beacon

- **Personal Capsule** (`LockedCapsulePH`) - station: Workshop, auto: 450s, manual: 5s
  - inputs: 2x Magnetic Coil
  - outputs: 1x Personal Capsule

- **Power Shuttle** (`PShuttlePH`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 6x Small Steel Part Casing, 6x Support Hardware, 1x Small Cargo Hold, 2x Semiconductor Substrate, 3x Wire
  - outputs: 1x Power Shuttle

- **Antimatter Core (full)** (`PowerToAntimatter`) - station: <bad>Cannot Craft In Beta</bad>, auto: 3000s, manual: 0s
  - inputs: 1x Antimatter Core (empty)
  - outputs: 1x Antimatter Core (full)

- **Freighter** (`Shuttle1PH`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 6x Small Steel Part Casing, 6x Support Hardware, 1x Small Cargo Hold, 2x Semiconductor Substrate, 3x Wire
  - outputs: 1x Freighter

## Craft_Parts (10)

- **LR "Raptor" Cockpit** (`Cockpit_LR2PH`) - station: Workshop, auto: 7200s, manual: 80s
  - inputs: 4x Titanium Part Casing, 32x Support Hardware
  - outputs: 1x LR "Raptor" Cockpit

- **Alloy X 8x3x2** (`Part_Mk1_AlloyX_Double`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 4x Small Alloy X Part Casing, 8x Support Hardware
  - outputs: 1x Alloy X 8x3x2

- **Alloy X 8x3x1** (`Part_Mk1_AlloyX_DoubleFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 4x Small Alloy X Part Casing, 4x Support Hardware
  - outputs: 1x Alloy X 8x3x1

- **Alloy X 6x3x2** (`Part_Mk1_AlloyX_Medium`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 3x Small Alloy X Part Casing, 6x Support Hardware
  - outputs: 1x Alloy X 6x3x2

- **Alloy X 6x3x1** (`Part_Mk1_AlloyX_MediumFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 3x Small Alloy X Part Casing, 3x Support Hardware
  - outputs: 1x Alloy X 6x3x1

- **Alloy X 4x3x2** (`Part_Mk1_AlloyX_Simple`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 2x Small Alloy X Part Casing, 4x Support Hardware
  - outputs: 1x Alloy X 4x3x2

- **Alloy X 4x3x1** (`Part_Mk1_AlloyX_SimpleFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 2x Small Alloy X Part Casing, 2x Support Hardware
  - outputs: 1x Alloy X 4x3x1

- **Alloy X 16x6x2** (`Part_Mk2_AlloyX_DoubleFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 4x Alloy X Part Casing, 16x Support Hardware
  - outputs: 1x Alloy X 16x6x2

- **Alloy X 12x6x2** (`Part_Mk2_AlloyX_MediumFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 3x Alloy X Part Casing, 12x Support Hardware
  - outputs: 1x Alloy X 12x6x2

- **Alloy X 8x6x2** (`Part_Mk2_AlloyX_SimpleFlat`) - station: Workshop, auto: 180s, manual: 2s
  - inputs: 2x Alloy X Part Casing, 8x Support Hardware
  - outputs: 1x Alloy X 8x6x2

## Craft_Patch (4)

- **Module Patch: Fuel Efficiency II** (`Patch_FuelEfficiency2PH`) - station: Workshop, auto: 360s, manual: 4s
  - inputs: 4x Module Patch: Fuel Efficiency I
  - outputs: 1x Module Patch: Fuel Efficiency II
  - note: Placé en Random Blueprint when the craft is right

- **Module Patch: Fuel Efficiency III** (`Patch_FuelEfficiency2PH1`) - station: Workshop, auto: 1800s, manual: 20s
  - inputs: 10x Module Patch: Fuel Efficiency II
  - outputs: 1x Module Patch: Fuel Efficiency III
  - note: Placé en Random Blueprint when the craft is right

- **Laser Patch: Mining Tier I** (`Patch_MiningTier1PH`) - station: Workshop, auto: 360s, manual: 4s
  - inputs: 1x Emerald, 1x Hyper Lens
  - outputs: 1x Laser Patch: Mining Tier I

- **Laser Patch: Mining Tier II** (`Patch_MiningTier2PH`) - station: Workshop, auto: 1800s, manual: 20s
  - inputs: 10x Laser Patch: Mining Tier I
  - outputs: 1x Laser Patch: Mining Tier II
  - note: Placé en Random Blueprint when the craft is right

## Craft_Recycle (7)

- **Aluminum Ingot (Aluminum Scraps)** (`RecycleAlu`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 5x Aluminum Scraps
  - outputs: 5x Aluminum Ingot

- **Aluminum Ingot (Industrial Rubble)** (`RecycleBuilding`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 4x Industrial Rubble
  - outputs: 2x Aluminum Ingot, 1x Copper Ingot, 5x Concrete

- **Iron Ingot (Iron Scraps)** (`RecycleIron`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 5x Iron Scraps
  - outputs: 5x Iron Ingot

- **Steel Ingot (Steel Scraps)** (`RecycleSteel`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 4x Steel Scraps
  - outputs: 4x Steel Ingot

- **Steel Ingot (Wrecked Hull)** (`RecycleSteelHull`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 4x Wrecked Hull
  - outputs: 2x Steel Ingot, 1x Aluminum Ingot, 1x Copper Ingot

- **Silicon Ingot (Huge Electronics Scraps)** (`RecycleSystem`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 3x Huge Electronics Scraps
  - outputs: 0x Silicon Ingot, 4x Copper Ingot

- **Titanium Ingot (Titanium Scraps)** (`RecycleTitanium`) - station: Recycler, auto: 675s, manual: 0s
  - inputs: 5x Titanium Scraps
  - outputs: 5x Titanium Ingot

## Craft_StudyCrystal (9)

- **Select... (Aquamarine)** (`StudyAquamarine`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Aquamarine
  - outputs: 1x Select...

- **Select... (Azurite Stone)** (`StudyAzurite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Azurite Stone
  - outputs: 1x Select...

- **Select... (Diamond)** (`StudyDiamond`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Diamond
  - outputs: 1x Select...

- **Select... (Emerald)** (`StudyEmerald`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Emerald
  - outputs: 1x Select...

- **Select... (Graphite Crystal)** (`StudyGraphite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Graphite Crystal
  - outputs: 1x Select...

- **Select... (Hematite)** (`StudyHematite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Hematite
  - outputs: 1x Select...

- **Select... (Malachite Stone)** (`StudyMalachite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Malachite Stone
  - outputs: 1x Select...

- **Select... (Pyrite)** (`StudyPyrite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Pyrite
  - outputs: 1x Select...

- **Select... (Quartz)** (`StudyQuartz`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Quartz
  - outputs: 1x Select...

## Craft_StudyMineral (7)

- **Select... (Calcified Invariant)** (`StudyCalcifiedInvariant`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Calcified Invariant
  - outputs: 1x Select...

- **Select... (Calcite)** (`StudyCalcite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Calcite
  - outputs: 1x Select...

- **Select... (Cinnabar)** (`StudyCinnabar`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Cinnabar
  - outputs: 1x Select...

- **Select... (Elmerium Nugget)** (`StudyElmerium`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Elmerium Nugget
  - outputs: 1x Select...

- **Select... (Kaolinite)** (`StudyKaolinite`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Kaolinite
  - outputs: 1x Select...

- **Select... (Silicate)** (`StudySandstone`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Silicate
  - outputs: 1x Select...

- **Select... (Turquoise)** (`StudyTurquoise`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Turquoise
  - outputs: 1x Select...

## Craft_StudyOrganic (5)

- **Select... (Rockwood Nut)** (`StudyRockwood_Seed`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Rockwood Nut
  - outputs: 1x Select...

- **Select... (Plain Pulp)** (`StudySpaceWheat_PlainPulp`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Plain Pulp
  - outputs: 1x Select...

- **Select... (Spacekorn Seed)** (`StudySpaceWheat_Raw`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Spacekorn Seed
  - outputs: 1x Select...

- **Select... (Sour Pulp)** (`StudySpaceWheat_SourPulp`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Sour Pulp
  - outputs: 1x Select...

- **Select... (Frost Pulp)** (`StudySpaceWheat_SourPulp1`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Frost Pulp
  - outputs: 1x Select...

## Craft_StudyQuest (1)

- **Select... (Possible Alien Artifact)** (`StudyQuestFakeArtefact`) - station: Laboratory, auto: 0s, manual: 0s
  - inputs: 1x Possible Alien Artifact
  - outputs: 1x Select...

## Craft_Tools (4)

- **Gravitron** (`GravitronPH`) - station: Workshop, auto: 900s, manual: 10s
  - inputs: 1x Simple Resource Detector, 1x Diamond, 2x Calcified Invariant, 3x Diffraction Grating
  - outputs: 1x Gravitron

- **Power Projector** (`PowerSharerPH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Power Projector

- **Stealth Micro-Projector** (`Stealth0PH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Stealth Micro-Projector

- **Stealth Macro-Projector** (`Stealth1PH`) - station: Workshop, auto: 720s, manual: 10s
  - inputs: 1x Small Module Kit, 2x Magnetic Coil
  - outputs: 1x Stealth Macro-Projector

## Virtual (1)

- **Quantum Beacon (Quantum Signature)** (`BeaconKeyPricer`) - station: (none), auto: 0s, manual: 0s
  - inputs: 5x Quantum Signature
  - outputs: 1x Quantum Beacon
  - note: Used to compute the price of Beacon Key automatically.

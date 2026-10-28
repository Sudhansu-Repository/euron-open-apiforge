/**
 * Named aliases over the generated OpenAPI types (`pnpm gen:api`). Nothing here is
 * hand-written: every shape comes from `schema.d.ts`, which is generated from
 * docs/api/openapi.yaml.
 */
import type { components } from "./schema";

type S = components["schemas"];

export type User = S["UserOut"];
export type UserCreate = S["UserCreate"];
export type UserUpdate = S["UserUpdate"];
export type Session = S["SessionOut"];
export type ApiKey = S["KeyOut"];
export type ApiKeyCreated = S["KeyCreated"];
export type ApiKeyIn = S["KeyIn"];
export type ApiKeyUpdate = S["KeyUpdate"];
export type AuditEntry = S["AuditOut"];
export type SystemInfo = S["SystemInfo"];

export type Overview = S["Overview"];
export type SpecChange = S["SpecChange"];

export type Project = S["ProjectOut"];
export type ProjectIn = S["ProjectIn"];
export type ProjectPatch = S["ProjectPatch"];
export type LatestSpec = S["LatestSpec"];
export type LatestGeneration = S["LatestGeneration"];
export type Example = S["ExampleOut"];
export type FromExampleIn = S["FromExampleIn"];

export type SpecVersion = S["SpecVersionOut"];
export type SpecDetail = S["SpecVersionDetail"];
export type SpecUploaded = S["SpecUploaded"];
export type SpecChanges = S["SpecChanges"];
export type SpecContent = S["SpecContent"];
export type SpecDiff = S["SpecDiff"];
export type Finding = S["Finding"];
export type Severity = Finding["severity"];
export type OperationSummary = S["OperationSummary"];
export type TagSummary = S["TagSummary"];
export type SchemeSummary = S["SchemeSummary"];
export type LintIn = S["LintIn"];
export type LintOut = S["LintOut"];

export type Generation = S["GenerationOut"];
export type GenerationDetail = S["GenerationDetail"];
export type GenerationIn = S["GenerationIn"];
export type GenerationOptions = S["GenerationOptions"];
export type GenerationStatus = Generation["status"];
export type GeneratedFile = S["GeneratedFileOut"];
export type FileOwner = GeneratedFile["owner"];
export type FileContent = S["FileContent"];

export type Role = NonNullable<UserCreate["role"]>;

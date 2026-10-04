/** React Query hooks. One place for cache keys so invalidation is obvious. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { staff } from "./api";

export const keys = {
  organizations: ["organizations"] as const,
  surveys: (orgId: string) => ["surveys", orgId] as const,
  survey: (id: string) => ["survey", id] as const,
  versions: (surveyId: string) => ["versions", surveyId] as const,
  version: (id: string) => ["version", id] as const,
  sections: (versionId: string) => ["sections", versionId] as const,
  results: (versionId: string) => ["results", versionId] as const,
  submissions: (versionId: string) => ["submissions", versionId] as const,
  submissionAnswers: (id: string) => ["submission-answers", id] as const,
  exports: (versionId: string) => ["exports", versionId] as const,
};

export const useOrganizations = () =>
  useQuery({ queryKey: keys.organizations, queryFn: staff.organizations });

export const useSurveys = (orgId: string | undefined) =>
  useQuery({
    queryKey: keys.surveys(orgId ?? ""),
    queryFn: () => staff.surveys(orgId as string),
    enabled: Boolean(orgId),
  });

export const useSurvey = (id: string | undefined) =>
  useQuery({
    queryKey: keys.survey(id ?? ""),
    queryFn: () => staff.survey(id as string),
    enabled: Boolean(id),
  });

export const useVersions = (surveyId: string | undefined) =>
  useQuery({
    queryKey: keys.versions(surveyId ?? ""),
    queryFn: () => staff.versions(surveyId as string),
    enabled: Boolean(surveyId),
  });

export const useVersion = (id: string | undefined) =>
  useQuery({
    queryKey: keys.version(id ?? ""),
    queryFn: () => staff.version(id as string),
    enabled: Boolean(id),
    // A published version is immutable, so once loaded it never needs
    // refetching. Drafts change on every edit.
    staleTime: (query) =>
      query.state.data?.status === "published" ? Infinity : 0,
  });

export const useSections = (versionId: string | undefined) =>
  useQuery({
    queryKey: keys.sections(versionId ?? ""),
    queryFn: () => staff.sections(versionId as string),
    enabled: Boolean(versionId),
  });

export const useResults = (versionId: string | undefined) =>
  useQuery({
    queryKey: keys.results(versionId ?? ""),
    queryFn: () => staff.results(versionId as string),
    enabled: Boolean(versionId),
    // Results are incrementally maintained server-side, so polling is cheap
    // and a live dashboard is the point.
    refetchInterval: 10_000,
  });

export const useSubmissions = (versionId: string | undefined) =>
  useQuery({
    queryKey: keys.submissions(versionId ?? ""),
    queryFn: () => staff.submissions(versionId as string),
    enabled: Boolean(versionId),
  });

export const useSubmissionAnswers = (id: string | undefined) =>
  useQuery({
    queryKey: keys.submissionAnswers(id ?? ""),
    queryFn: () => staff.submissionAnswers(id as string),
    enabled: Boolean(id),
  });

export const useExports = (versionId: string | undefined, poll: boolean) =>
  useQuery({
    queryKey: keys.exports(versionId ?? ""),
    queryFn: () => staff.exports(versionId as string),
    enabled: Boolean(versionId),
    // Generation is a background job, so the list polls only while
    // something is actually in flight.
    refetchInterval: poll ? 2000 : false,
  });

export function usePublish(versionId: string, surveyId: string | undefined) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => staff.publish(versionId),
    onSuccess: () => {
      client.invalidateQueries({ queryKey: keys.version(versionId) });
      client.invalidateQueries({ queryKey: keys.sections(versionId) });
      if (surveyId) {
        client.invalidateQueries({ queryKey: keys.versions(surveyId) });
        client.invalidateQueries({ queryKey: keys.survey(surveyId) });
      }
    },
  });
}

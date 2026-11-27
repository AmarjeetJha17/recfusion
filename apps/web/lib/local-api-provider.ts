import {
  ERROR_SCHEMA,
  parseRecommendationResponse,
  type RecommendationProvider,
} from "@/lib/recommendation-provider";

const LOCAL_API_URL = "http://127.0.0.1:8000/v1/recommendations";
const REQUEST_TIMEOUT_MS = 8_000;
const MAX_REQUEST_BYTES = 16_384;

type ApiErrorEnvelope = {
  schema_version: typeof ERROR_SCHEMA;
  error: { code: string; message: string };
};

export class LocalRecommendationApiError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LocalRecommendationApiError";
  }
}

export const localApiRecommendationProvider: RecommendationProvider = Object.freeze({
  async recommend(request, options) {
    if (process.env.NODE_ENV === "production") {
      throw new LocalRecommendationApiError(
        "Local API mode is available only in a development build.",
      );
    }

    const body = JSON.stringify(request);
    if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) {
      throw new LocalRecommendationApiError("The request is larger than the local API allows.");
    }

    const controller = new AbortController();
    const abortFromCaller = () => controller.abort(options?.signal?.reason);
    options?.signal?.addEventListener("abort", abortFromCaller, { once: true });
    const timeout = setTimeout(() => controller.abort("timeout"), REQUEST_TIMEOUT_MS);

    try {
      const response = await fetch(LOCAL_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        signal: controller.signal,
        cache: "no-store",
      });
      const payload: unknown = await response.json().catch(() => undefined);

      if (!response.ok) {
        const code = readApiErrorCode(payload);
        if (response.status === 503 && code === "CONCURRENCY_LIMIT_EXCEEDED") {
          throw new LocalRecommendationApiError(
            "The local demo is temporarily at capacity. Try again shortly.",
          );
        }
        if (response.status === 404) {
          throw new LocalRecommendationApiError(
            "The selected synthetic context is not available in the local catalog.",
          );
        }
        if (response.status === 422) {
          throw new LocalRecommendationApiError(
            "The local API rejected this request. Review the selected options and try again.",
          );
        }
        if (response.status === 503) {
          throw new LocalRecommendationApiError("The local recommendation service is unavailable.");
        }
        throw new LocalRecommendationApiError("The local API could not complete this request.");
      }

      try {
        return parseRecommendationResponse(payload);
      } catch {
        throw new LocalRecommendationApiError(
          "The local API returned a response that does not match the v1 contract.",
        );
      }
    } catch (error) {
      if (error instanceof LocalRecommendationApiError) throw error;
      if (controller.signal.aborted) {
        if (options?.signal?.aborted) throw error;
        throw new LocalRecommendationApiError(
          "The local API request timed out. Check that the development service is running.",
        );
      }
      throw new LocalRecommendationApiError(
        "The local API is unavailable. Start the development service or switch to fixtures.",
      );
    } finally {
      clearTimeout(timeout);
      options?.signal?.removeEventListener("abort", abortFromCaller);
    }
  },
});

function readApiErrorCode(value: unknown): string | undefined {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
  const envelope = value as Partial<ApiErrorEnvelope>;
  if (
    envelope.schema_version !== ERROR_SCHEMA ||
    typeof envelope.error !== "object" ||
    envelope.error === null ||
    typeof envelope.error.code !== "string"
  ) {
    return undefined;
  }
  return envelope.error.code;
}

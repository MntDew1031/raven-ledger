import { ApiError } from "@/lib/api";

/**
 * Registration failures are shown to anonymous visitors, so they stay generic
 * unless the backend sent a message that is safe and useful to repeat.
 */
export function registrationMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    if (reason.status === 409) {
      return "An account already exists for that email. Sign in instead.";
    }
    if (
      reason.status === 403 ||
      reason.status === 404 ||
      reason.status === 422 ||
      reason.status === 429
    ) {
      return reason.message;
    }
  }
  return "Could not create the account. Please try again.";
}

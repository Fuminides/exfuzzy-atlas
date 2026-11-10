/** An error from the data layer. `status` is the HTTP status the live API would send (null: the data could not be reached). */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    /** The raw, language-independent `detail` (what the API puts in its error body), when there is one. */
    readonly detail?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

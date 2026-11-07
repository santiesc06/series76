package io.github.santiesc06.series76.data

import io.github.santiesc06.series76.data.api.ErrorResponse
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json
import retrofit2.HttpException
import java.io.IOException
import java.net.SocketTimeoutException

/** A user-facing failure. `code` follows the backend's error codes (design C4a) or a local one. */
data class AppError(val code: String, val message: String)

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>
    data class Err(val error: AppError) : ApiResult<Nothing>
}

/** Runs one API call and turns every failure into an [AppError] the UI can show with a retry. */
suspend fun <T> apiCall(json: Json, block: suspend () -> T): ApiResult<T> =
    try {
        ApiResult.Ok(block())
    } catch (e: CancellationException) {
        throw e
    } catch (e: HttpException) {
        ApiResult.Err(httpError(json, e))
    } catch (e: SocketTimeoutException) {
        ApiResult.Err(AppError("timeout", "The server took too long to answer. Try again."))
    } catch (e: IOException) {
        ApiResult.Err(
            AppError("network", "Can't reach the server. Check that the backend is running."),
        )
    } catch (e: SerializationException) {
        ApiResult.Err(AppError("bad_response", "The server sent an unexpected response."))
    }

private fun httpError(json: Json, e: HttpException): AppError {
    val body = e.response()?.errorBody()?.string()
    val parsed = body?.let { runCatching { json.decodeFromString<ErrorResponse>(it) }.getOrNull() }
    return if (parsed != null) {
        AppError(parsed.error.code, parsed.error.message)
    } else {
        AppError("http_${e.code()}", "The server answered with an error (HTTP ${e.code()}).")
    }
}

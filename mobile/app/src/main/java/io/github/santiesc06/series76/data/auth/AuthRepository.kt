package io.github.santiesc06.series76.data.auth

import io.github.santiesc06.series76.data.ApiResult
import io.github.santiesc06.series76.data.apiCall
import io.github.santiesc06.series76.data.api.LoginRequest
import io.github.santiesc06.series76.data.api.Series76Api
import io.github.santiesc06.series76.data.api.UserOut
import kotlinx.serialization.json.Json
import javax.inject.Inject
import javax.inject.Singleton

/** Login, logout and the signed-in user, over the `api/auth` endpoints (US-21). */
@Singleton
class AuthRepository @Inject constructor(
    private val api: Series76Api,
    private val json: Json,
    private val session: AuthSession,
) {
    /** On success the session is saved and the app switches to the conversations list. */
    suspend fun login(email: String, password: String): ApiResult<Unit> {
        val result = apiCall(json) { api.login(LoginRequest(email.trim(), password)) }
        if (result is ApiResult.Ok) session.signIn(result.value.token, result.value.user.toUser())
        return when (result) {
            is ApiResult.Ok -> ApiResult.Ok(Unit)
            is ApiResult.Err -> result
        }
    }

    /**
     * Signs out locally at once, then revokes the token on the server (US-21 AC8). If the server
     * cannot be reached the token still expires on its own (7 days, design U1).
     */
    suspend fun logout() {
        val token = session.token ?: return
        session.signOut()
        apiCall(json) { api.logout("Bearer $token") }
    }

    /** Checks the saved token and refreshes the name shown; a 401 signs out via the interceptor. */
    suspend fun refreshUser() {
        val result = apiCall(json) { api.me() }
        if (result is ApiResult.Ok) session.updateUser(result.value.toUser())
    }

    private fun UserOut.toUser() = SignedInUser(email = email, name = name)
}

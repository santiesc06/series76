package io.github.santiesc06.series76.data.auth

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject

/**
 * Adds `Authorization: Bearer <token>` to every API request (US-21, design U4) and signs the
 * user out when the server answers 401 to that token (US-21 AC7: back to the login screen).
 *
 * Requests that already carry an Authorization header (logout) or that are sent while signed out
 * (login) are left alone, so a wrong password never counts as an expired session.
 */
class AuthInterceptor @Inject constructor(private val session: AuthSession) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val token = if (original.header(AUTHORIZATION) == null) session.token else null
        val request = if (token != null) {
            original.newBuilder().header(AUTHORIZATION, "Bearer $token").build()
        } else {
            original
        }
        val response = chain.proceed(request)
        if (response.code == 401 && token != null) session.onUnauthorized(token)
        return response
    }

    private companion object {
        const val AUTHORIZATION = "Authorization"
    }
}

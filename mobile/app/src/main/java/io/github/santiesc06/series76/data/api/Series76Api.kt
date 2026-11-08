package io.github.santiesc06.series76.data.api

import retrofit2.http.Body
import retrofit2.http.GET
import okhttp3.MultipartBody
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path

/** The backend's REST API (design C1). */
interface Series76Api {
    @POST("api/auth/login")
    suspend fun login(@Body body: LoginRequest): LoginResponse

    /** Takes the token explicitly: the app has already forgotten it when this is sent. */
    @POST("api/auth/logout")
    suspend fun logout(@Header("Authorization") authorization: String)

    @GET("api/auth/me")
    suspend fun me(): UserOut

    /** Voice message to text (US-22); the audio is not stored on the server (design V5). */
    @Multipart
    @POST("api/transcribe")
    suspend fun transcribe(@Part audio: MultipartBody.Part): TranscribeResponse

    @POST("api/conversation")
    suspend fun converse(@Body body: ConversationRequest): ConversationResponse

    @GET("api/sessions")
    suspend fun sessions(): List<SessionSummary>

    @GET("api/sessions/{id}/messages")
    suspend fun sessionMessages(@Path("id") sessionId: String): SessionMessages

    @GET("api/messages/{id}/debug")
    suspend fun messageDebug(@Path("id") messageId: String): DebugInfo
}

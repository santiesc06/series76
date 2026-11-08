package io.github.santiesc06.series76.data

import io.github.santiesc06.series76.data.api.ConversationRequest
import io.github.santiesc06.series76.data.api.ConversationResponse
import io.github.santiesc06.series76.data.api.DebugInfo
import io.github.santiesc06.series76.data.api.Series76Api
import io.github.santiesc06.series76.data.api.SessionMessages
import io.github.santiesc06.series76.data.api.SessionSummary
import io.github.santiesc06.series76.data.api.TranscribeResponse
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/** The backend is the source of truth for conversations (design M2): no local database. */
@Singleton
class ChatRepository @Inject constructor(
    private val api: Series76Api,
    private val json: Json,
) {
    suspend fun sessions(): ApiResult<List<SessionSummary>> = apiCall(json) { api.sessions() }

    suspend fun history(sessionId: String): ApiResult<SessionMessages> =
        apiCall(json) { api.sessionMessages(sessionId) }

    suspend fun send(sessionId: String?, query: String): ApiResult<ConversationResponse> =
        apiCall(json) { api.converse(ConversationRequest(sessionId = sessionId, query = query)) }

    /** Uploads one recording (AAC in M4A, design V7) and returns its text (US-22). */
    suspend fun transcribe(file: File): ApiResult<TranscribeResponse> = apiCall(json) {
        val body = file.asRequestBody("audio/mp4".toMediaType())
        api.transcribe(MultipartBody.Part.createFormData("audio", file.name, body))
    }

    suspend fun debug(messageId: String): ApiResult<DebugInfo> =
        apiCall(json) { api.messageDebug(messageId) }
}

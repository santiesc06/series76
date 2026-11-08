package io.github.santiesc06.series76.data.auth

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton

data class SignedInUser(val email: String, val name: String)

sealed interface AuthState {
    /** Reading the saved token at start-up. */
    data object Loading : AuthState

    /** `expired`: the server rejected the saved token, so the login screen says so (US-21 AC7). */
    data class SignedOut(val expired: Boolean = false) : AuthState

    data class SignedIn(val user: SignedInUser) : AuthState
}

/**
 * Who is signed in, and the token sent with every request (US-21 AC7, design U6).
 *
 * The token is kept in Jetpack DataStore (app-private, excluded from backup in
 * the backup rules in `res/xml`) so it survives restarts, and in memory for [AuthInterceptor], which runs
 * on OkHttp threads and cannot suspend. This class never calls the API, so the interceptor can
 * depend on it without a dependency cycle; [AuthRepository] does the network part.
 */
@Singleton
class AuthSession @Inject constructor(private val store: DataStore<Preferences>) {

    private val _state = MutableStateFlow<AuthState>(AuthState.Loading)
    val state: StateFlow<AuthState> = _state.asStateFlow()

    @Volatile
    var token: String? = null
        private set

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Loads the saved token once, at start-up. A token that has expired is caught by the API. */
    suspend fun restore() {
        if (_state.value != AuthState.Loading) return
        val prefs = store.data.catch { if (it is IOException) emit(emptyPreferences()) else throw it }
            .first()
        val saved = prefs[TOKEN]
        val user = SignedInUser(email = prefs[EMAIL].orEmpty(), name = prefs[NAME].orEmpty())
        synchronized(this) {
            if (_state.value != AuthState.Loading) return
            token = saved
            _state.value = if (saved != null) AuthState.SignedIn(user) else AuthState.SignedOut()
        }
    }

    suspend fun signIn(token: String, user: SignedInUser) {
        store.edit {
            it[TOKEN] = token
            it[EMAIL] = user.email
            it[NAME] = user.name
        }
        synchronized(this) {
            this.token = token
            _state.value = AuthState.SignedIn(user)
        }
    }

    /** Keeps the saved name and email in step with the server (`GET /api/auth/me`). */
    suspend fun updateUser(user: SignedInUser) {
        synchronized(this) {
            if (_state.value !is AuthState.SignedIn) return
            _state.value = AuthState.SignedIn(user)
        }
        store.edit {
            it[EMAIL] = user.email
            it[NAME] = user.name
        }
    }

    /** Forgets the token at once (no request uses it after this returns), then clears storage. */
    fun signOut(expired: Boolean = false) {
        val dropped = synchronized(this) {
            token.also {
                token = null
                _state.value = AuthState.SignedOut(expired)
            }
        }
        // Clear only the token dropped here, in case the user signs in again before this runs.
        scope.launch { store.edit { if (it[TOKEN] == dropped) it.clear() } }
    }

    /**
     * The server answered 401 to a request sent with [sentToken]. Only that token is dropped: a 401
     * that arrives after the user already signed in again must not sign the new session out.
     */
    fun onUnauthorized(sentToken: String) {
        synchronized(this) {
            if (sentToken == token) signOut(expired = true)
        }
    }

    private companion object {
        val TOKEN = stringPreferencesKey("token")
        val EMAIL = stringPreferencesKey("email")
        val NAME = stringPreferencesKey("name")
    }
}

package io.github.santiesc06.series76.navigation

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import io.github.santiesc06.series76.data.auth.AuthRepository
import io.github.santiesc06.series76.data.auth.AuthSession
import io.github.santiesc06.series76.data.auth.AuthState
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Decides between the login screen and the app (US-21 AC7). Lives as long as the activity. */
@HiltViewModel
class AppViewModel @Inject constructor(
    private val session: AuthSession,
    private val repository: AuthRepository,
) : ViewModel() {

    val auth: StateFlow<AuthState> = session.state

    init {
        viewModelScope.launch {
            session.restore()
            // A saved token opens the app at once; the server then confirms it. A 401 here (or on
            // any later request) returns to the login screen with "session expired".
            if (session.state.value is AuthState.SignedIn) repository.refreshUser()
        }
    }

    fun logout() {
        viewModelScope.launch { repository.logout() }
    }
}
